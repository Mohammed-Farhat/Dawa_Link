"""Checking a reply before a client sees it (docs/07 §7.2, API-D6).

The model's reply is only a proposal until it has passed here. Each failed check is a
`Violation` with a sentence the model can act on: it gets one chance to fix its reply,
and after that a text written by us is sent instead (AG-D9).
"""

import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from dawalink.agent.guards.clinical import clinical_reasons
from dawalink.agent.guards.grounding import claims_completed, comparison_errors
from dawalink.agent.guards.language import language_of, looks_arabizi
from dawalink.agent.guards.redact import has_personal_details
from dawalink.agent.tools import ALL, Reply
from dawalink.domain.vocabulary import ProposalKind
from dawalink.services import proposals
from dawalink.services.context import Tx

CARD, PII, CLINICAL, LANGUAGE, RECOMMENDED, SCHEMA, INTERNALS, NO_CARD = (
    "card",
    "pii",
    "clinical",
    "language",
    "recommended",
    "schema",
    "internals",
    "no_card",
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
# "The card is below", "here is the card": the reply points at a card of this message.
# A general sentence about cards ("only your tap on a card reserves") doesn't.
POINTS_AT_A_CARD = re.compile(
    r"\bcards?\b[^.!?\n]{0,40}\b(?:below|underneath|ta7e?t|taht)\b|"
    r"\b(?:below|here(?: is|'s| are))\b[^.!?\n]{0,30}\bcards?\b|"
    r"\bhere(?: is|'s| are)\b[^.!?\n]{0,45}\b(?:cancellation|reservation) card\b|"
    r"(?:البطاقة|البطاقات|الكرت)[^.!?؟\n]{0,40}(?:أدناه|تحت|بالأسفل)",
    re.IGNORECASE,
)
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


# Words French can't do without, and that English and Arabizi don't use.
_FRENCH = re.compile(
    r"\b(?:vous|nous|est|sont|les|des|une|pour|avec|dans|chez|votre|vos|pas|je|peux|"
    r"quel(?:le)?s?|jours?|ordonnance|pharmacien(?:ne)?|médecin|disponible)\b",
    re.IGNORECASE,
)


def looks_french(text: str) -> bool:
    """Is this written in French? Several French words, and a fair share of all words.

    A rule of thumb for one case: a client who writes Arabizi or English, answered in
    French (seen in the evaluation). A French word here and there is how people write.
    """
    words = re.findall(r"[A-Za-zÀ-ÿ']+", text)
    french = len(_FRENCH.findall(text))
    return french >= 4 and french * 8 >= len(words)


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
    found_something: bool = False,
    tool_answers: Sequence[str] = (),
    language: str | None = None,
    on_foot: bool = False,
    preference: str | None = None,
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

    elif not any(
        known[proposal_id].agent_run_id == run_id for proposal_id in usable
    ) and proposals.made_in_run(tx, run_id):
        # Seen on real runs: "here is the reservation card" next to an older card; and, on
        # a simulated day, a plan told in words with its cards made and none shown, which
        # left the client with nothing to tap.
        violations.append(
            Violation(
                CARD,
                "You made a card in this turn, but proposal_ids doesn't show it. Put the "
                "proposal_id(s) from this turn's tool results in proposal_ids; older cards "
                "may stay next to them.",
            )
        )

    if found_something and not cleaned.proposal_ids and not proposals.made_in_run(tx, run_id):
        # Seen on simulated days: a plan told in words, pharmacies and prices and all,
        # and no card. The request then ran out with nothing the client could tap.
        violations.append(
            Violation(
                NO_CARD,
                "You found where the medicine is in this turn, but your reply shows no "
                "card, so the client can't reserve anything. Make the cards now "
                "(propose_plan for a plan, propose_reservation for an option) and show "
                "them. If nothing you found fits what the client told you, say that "
                "plainly instead of listing pharmacies.",
            )
        )

    if not cleaned.proposal_ids and POINTS_AT_A_CARD.search(cleaned.text):
        # Seen in the safety evaluation: a tool refused to make a cancel card, and the
        # reply still said "the card is below".
        violations.append(
            Violation(
                CARD,
                "Your reply points at a card, but it shows none. If a tool gave you a "
                "proposal_id in this turn, put it in proposal_ids. If the tool refused, "
                "say what you couldn't do, and don't mention a card.",
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

    # A cheapest preference cannot be silently replaced by a balanced recommendation.
    chosen_preference = (
        cleaned.case_notes.preference
        if cleaned.case_notes and cleaned.case_notes.preference
        else preference
    )
    if chosen_preference == "cheapest":
        options = []
        for answer in tool_answers:
            parsed = json.loads(answer)
            if isinstance(parsed, dict) and isinstance(parsed.get("options"), list):
                options = parsed["options"]
        for proposal_id in usable:
            payload = known[proposal_id].payload
            if not payload.get("card", {}).get("recommended") or "price_lbp_shown" not in payload:
                continue
            for option in options:
                if (
                    str(option.get("product_id")) == str(payload.get("product_id"))
                    and not option.get("is_alternative")
                    and option.get("available", 0) >= payload.get("qty", 1)
                    and payload.get("pickup_day") in option.get("pickup_days_allowed", [])
                    and (price := re.match(r"([\d,]+) LBP", option.get("price", "")))
                    and int(price[1].replace(",", "")) < payload["price_lbp_shown"]
                ):
                    violations.append(
                        Violation(
                            "preference",
                            "The client asked for cheapest, but you recommended a "
                            "more expensive option of the same product. Recommend the cheapest "
                            "feasible option or explain a specific unmet constraint.",
                        )
                    )
                    break

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
    if claims_completed(cleaned.text):
        violations.append(
            Violation(
                "grounding",
                "Do not claim a reservation or cancellation completed. You propose cards; "
                "only the client tap executes them. Describe the proposal or the tool refusal.",
            )
        )
    for error in comparison_errors(cleaned.text, tool_answers, on_foot=on_foot):
        # A limited parser cannot prove a claim false merely because association
        # failed. Such claims stay flagged by the scorer for mandatory manual review.
        if not error.startswith("Unresolved "):
            violations.append(Violation("grounding", error))
    wanted_language = language_of(client_text or "", language)
    if wanted_language == "english" and looks_arabizi(cleaned.text):
        violations.append(
            Violation(LANGUAGE, "The client wrote English. Keep the explanation in English.")
        )
    if wanted_language == "arabizi" and not looks_arabizi(cleaned.text):
        violations.append(
            Violation(
                LANGUAGE,
                "Answer in Lebanese Arabizi, including the explanation, "
                "not just a greeting. Keep Latin letters.",
            )
        )
    wanted, written = script_of(client_text or ""), script_of(cleaned.text)
    if wanted == "latin" and looks_french(cleaned.text) and not looks_french(client_text or ""):
        violations.append(
            Violation(
                LANGUAGE,
                "The client didn't write in French. Answer in their own language: English "
                "if they wrote English, Lebanese Arabic in Latin letters if they wrote "
                "Arabizi.",
            )
        )
    elif wanted and written and wanted != written:
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
