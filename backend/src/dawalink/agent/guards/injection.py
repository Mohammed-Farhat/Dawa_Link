"""Flagging messages that try to give the agent orders (docs/07 §7.1, AG-D7).

A flagged message is **not blocked**: it is handled as ordinary data, and the flag is
counted. Blocking by keyword breaks innocent messages and is easy to get around. The real
defence is structural: the agent has no tool that can do harm, every tool is scoped to
the client, and a card is checked again when it is tapped.
"""

import re

_PATTERNS = (
    r"ignore\s+(?:all\s+|any\s+|the\s+|your\s+)*(?:previous|prior|above|earlier)",
    r"disregard\s+(?:all\s+|any\s+|the\s+|your\s+)*(?:previous|prior|above|instructions|rules)",
    r"forget\s+(?:all\s+|your\s+|the\s+)*(?:instructions|rules|prompt)",
    r"system\s+prompt",
    r"(?:reveal|show|print|repeat)\s+(?:me\s+)?(?:your|the)\s+(?:prompt|instructions|rules)",
    r"you\s+are\s+now\b",
    r"\bact\s+as\s+(?:an?\s+)?(?:admin|administrator|developer|pharmacist|doctor|system)",
    r"developer\s+mode",
    r"\bjailbreak",
    r"\bDAN\b",
    r"new\s+instructions?\s*:",
    r"</?\s*(?:system|assistant|instructions?)\s*>",
    # Arabizi
    r"\bnsa\s+(?:kel|kil)\s+(?:shi|l\s*ta3limet|el\s*ta3limet)",
    r"\btjehal\s+(?:kel|kil|l|el)",
    r"\b(?:ghayyer|8ayyer)\s+(?:l|el)\s*(?:2awe3ed|ta3limet|awe3ed)",
    r"\benta\s+hala2\b",
    # Arabic
    r"تجاهل\s+(?:كل\s+)?(?:التعليمات|القواعد|ما سبق)",
    r"انس[َى]?\s+(?:كل\s+)?(?:التعليمات|القواعد)",
    r"أنت\s+الآن",
    r"تعليمات\s+النظام",
)
_INJECTION = re.compile("|".join(f"(?:{pattern})" for pattern in _PATTERNS), re.IGNORECASE)


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text))
