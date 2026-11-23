"""Review candidates, never an automatic assertion of semantic correctness."""

import re
from typing import Any


def review_flags(reply: str, language: str) -> dict[str, Any]:
    candidates = []
    if re.search(r"ce m[ée]dicament|pour chercher|dis[- ]moi|ordonnance", reply, re.I):
        candidates.append("possible_unwanted_french")
    if language == "english" and re.search(
        r"\b(?:3ande|baddi|siyyara|lyom|bukra|ba3d|le2e|bil siyyara)\b", reply, re.I
    ):
        candidates.append("possible_english_to_arabizi_switch")
    if language == "arabizi" and re.search(r"\b(?:I found|I recommend|please tell me)\b", reply):
        candidates.append("possible_arabizi_to_english_switch")
    if re.search(
        r"(?:all|every|any|no) medicines?[^.!?\n]{0,80}prescription|"
        r"ma fi[^.!?\n]{0,30}(?:2ayy|ayy)[^.!?\n]{0,30}dawa[^.!?\n]{0,60}wasafa|"
        r"كل الأدوية[^.!؟\n]{0,60}وصفة",
        reply,
        re.I,
    ):
        candidates.append("unsupported_blanket_prescription_claim")
    return {
        "candidate_issues": candidates,
        "review_needed": bool(candidates),
        "automatic_checks_incomplete": ["language_semantics", "general_factuality"],
        "manual_verdict": None,
    }
