"""Checking a reply before a client sees it (docs/07 §7.2, API-D6).

The model's reply is only a proposal until it has passed here. Each failed check is a
`Violation` with a sentence the model can act on: it gets one chance to fix its reply,
and after that a text written by us is sent instead (AG-D9).
"""

import re
import uuid
from dataclasses import dataclass

from dawalink.agent.guards.clinical import clinical_reasons
from dawalink.agent.guards.redact import has_personal_details
from dawalink.agent.tools import ALL, Reply
from dawalink.domain.vocabulary import ProposalKind
from dawalink.services import proposals
from dawalink.services.context import Tx

CARD, PII, CLINICAL, LANGUAGE, RECOMMENDED, SCHEMA, INTERNALS = (
    "card",
    "pii",
    "clinical",
    "language",
    "recommended",
    "schema",
    "internals",
)

_MARKDOWN_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_HTML_TAG = re.compile(r"<[^>]{1,200}>")
_URL = re.compile(r"(?:(?:https?|ftp)://|www\.)\S+", re.IGNORECASE)
_ARABIC = re.compile(r"[؀-ۿ]")
# A tool written out as text, a raw ID or a bit of JSON: the machinery, not a message.
_INTERNALS = re.compile(
    r"\b(?:" + "|".join(tool.name for tool in ALL) + r"|reply)\(|"
    r"</?tool_call>|\bproposal_ids?\b|\bquick_replies\b|\bcase_notes\b|"
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|"
    r"\{\s*[\"'](?:name|arguments|tool|text)[\"']\s*:",
    re.IGNORECASE,
)
_LATIN = re.compile(r"[A-Za-z]")
# A quick reply that would say "the pharmacist agreed" or reserve a brand, in one tap.
_CLAIMS_THE_CALL = re.compile(
    # The pharmacist, not the pharmacy ("saydaliyye", "صيدلية"): [Call the pharmacy] is fine.
    r"\bpharmacist\b|\bpharmacien(?:ne)?\b|\bsa[yi]dal[ei]\b|صيدلي(?!ة)|صيدلاني|"
    r"\breserve\b|\bbook\b|\b[ei]?7jez\w*|احجز|حجز",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Violation:
    type: str
    # Said to the model, so it can fix its reply.
    feedback: str


@dataclass(frozen=True)
class Checked:
    reply: Reply
    violations: tuple[Violation, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


def plain(text: str) -> str:
    """The text with nothing a browser could turn into a link or an image (TM-D5).

    Replies are shown as plain text anyway; removing links here means a client is never
    shown an address the model was talked into writing.
    """
    text = _MARKDOWN_LINK.sub(lambda match: match.group(1), text)
    text = _HTML_TAG.sub("", text)
    text = _URL.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def script_of(text: str) -> str | None:
    """ "arabic" or "latin": the script most of the letters are in. None: no letters."""
    arabic, latin = len(_ARABIC.findall(text)), len(_LATIN.findall(text))
    if arabic + latin == 0:
        return None
    return "arabic" if arabic > latin else "latin"


def check(
    tx: Tx,
    reply: Reply,
    *,
    conversation_id: uuid.UUID,
    client_id: uuid.UUID,
    run_id: uuid.UUID,
    client_text: str | None,
) -> Checked:
    """The reply with links removed, and everything that is wrong with it."""
    cleaned = reply.model_copy(
        update={
            "text": plain(reply.text),
            "quick_replies": [chip for chip in map(plain, reply.quick_replies) if chip],
        }
    )
    violations: list[Violation] = []
    if not cleaned.text:
        violations.append(Violation(SCHEMA, "The reply text is empty. Write a short message."))

    # Cards: only stored proposals of this conversation and client, still open (INV-21).
    known = proposals.of_conversation(tx, conversation_id, cleaned.proposal_ids)
    usable = [
        proposal_id
        for proposal_id in cleaned.proposal_ids
        if proposal_id in known
        and known[proposal_id].client_id == client_id
        and proposals.state_of(tx, known[proposal_id]) == "open"
    ]
    if len(usable) != len(cleaned.proposal_ids):
        violations.append(
            Violation(
                CARD,
                "proposal_ids holds IDs that aren't open cards of this conversation. Use only "
                "proposal IDs returned by tools in this turn, or leave the list empty.",
            )
        )

    elif (
        usable
        and not any(known[proposal_id].agent_run_id == run_id for proposal_id in usable)
        and proposals.made_in_run(tx, run_id)
    ):
        # Seen on a real run: "here is the reservation card", next to an older card.
        violations.append(
            Violation(
                CARD,
                "You made a card in this turn, but proposal_ids shows only older cards. Show "
                "the card you just made (its proposal_id from this turn's tool result); "
                "older cards may stay next to it.",
            )
        )

    # Next to an "another brand" card, no quick reply may say the pharmacist agreed or
    # reserve the brand: one tap would claim a call that never happened (R-C10).
    shows_another_brand = any(
        known[proposal_id].kind == ProposalKind.OTHER_BRAND.value for proposal_id in usable
    )
    if shows_another_brand and any(_CLAIMS_THE_CALL.search(chip) for chip in cleaned.quick_replies):
        violations.append(
            Violation(
                CARD,
                "Next to another brand's card, don't offer a quick reply that says the "
                "pharmacist agreed or that reserves the brand. The client writes that "
                "themselves after calling the pharmacy.",
            )
        )

    # One recommendation per medicine (N-45).
    recommended: dict[str, int] = {}
    for proposal_id in usable:
        proposal = known[proposal_id]
        if not proposal.payload.get("card", {}).get("recommended"):
            continue
        medicine = str(proposal.payload.get("product_id"))
        recommended[medicine] = recommended.get(medicine, 0) + 1
    if any(count > 1 for count in recommended.values()):
        violations.append(
            Violation(RECOMMENDED, "Recommend one pharmacy per medicine, not several.")
        )

    everything = " \n ".join([cleaned.text, *cleaned.quick_replies])
    if _INTERNALS.search(everything):
        violations.append(
            Violation(
                INTERNALS,
                "The text shows tool names, IDs or raw data. Write only what a person "
                "should read, and call tools through the tool interface.",
            )
        )
    if has_personal_details(everything):
        violations.append(
            Violation(PII, "Remove every email address, phone number and coordinate.")
        )
    if clinical_reasons(everything):
        violations.append(
            Violation(
                CLINICAL,
                "This reads as medical advice (a dose, how often, safety, or what a medicine is "
                "good for). Say you can't advise on that and that a pharmacist or doctor can, "
                "then offer to keep searching.",
            )
        )
    wanted, written = script_of(client_text or ""), script_of(cleaned.text)
    if wanted and written and wanted != written:
        violations.append(
            Violation(
                LANGUAGE,
                "Answer in the client's own language and script: "
                + (
                    "Arabic script."
                    if wanted == "arabic"
                    else "Latin letters (English or Arabizi)."
                ),
            )
        )
    return Checked(cleaned, tuple(violations))
