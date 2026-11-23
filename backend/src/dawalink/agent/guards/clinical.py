"""Catching medical advice in a reply (docs/07 §7.2, AG-D8; decision log G3).

Rules first: precise patterns for the ways advice is actually given, in English, Arabizi
and Arabic. They are written so that plain logistics text is not caught: a product's
strength ("Augmentin 1g · 14 tablets"), a quantity ("2 packs"), how long a box must last
("for 7 days"), opening hours ("open daily"), or the prescription notice.

A reply that itself refuses ("I can't advise on doses") mentions the same words on
purpose, so a sentence with a refusal in it is not checked for the softer patterns.
"""

import re
from collections.abc import Iterable

_APOSTROPHE = "(?:'|’)?"  # noqa: RUF001  (phones type the curly one)
_NUMBER = r"\d+(?:[.,]\d+)?"
# A metric amount always has its number: "500 mg". Without one, "g" would match any word.
_METRIC = rf"{_NUMBER}\s*(?:mg|mcg|µg|g|ml|iu)\b"
_COUNTED = (
    r"(?:tablets?|tabs?|pills?|capsules?|caps|drops?|puffs?|spoons?|"
    r"7abbe|7abbet|7abbat|habbe|habbet|habbat|ma3la2a|ma3la2it|"
    r"حبة|حبات|حبوب|ملعقة|نقطة|نقط)"
)
# "Two pills" in one word.
_DUAL = r"(?:7abbten|7abbtein|habbten|habbtein|حبتين|ملعقتين)"
# An amount to swallow: "2 tablets", "7abbten". Not a strength: "500 mg" is also how a
# product is named.
_UNITS = rf"(?:\b(?:{_NUMBER}|one|two|three|half|noss)\s*{_COUNTED}(?!\w)|(?<!\w){_DUAL}(?!\w))"
_SOME = rf"(?:{_METRIC}|{_UNITS})"
# How often, with a count: "twice a day", "3 times daily", "marrten bil nhar".
_FREQUENCY = (
    r"(?:\b(?:once|twice|thrice|\d+\s*(?:x|times?))\s*(?:a|per|every|each)?\s*"
    r"(?:day|daily|week|night|morning)\b|\b\d+\s*(?:per|a)\s+day\b|\b(?:bid|tid|qid)\b|"
    r"\b(?:marra|marrten|marrtein|tlet\s+marrat|\d+\s+marrat)\s+"
    r"(?:bi?l?\s*(?:nhar|yom|yawm|jem3a)|k[ei]l\s+yom)\b|"
    r"(?:مرة|مرتين|ثلاث\s+مرات|\d+\s+مرات)\s+(?:باليوم|بالنهار|يوميا|كل\s+يوم))"
)
# "Daily" on its own says nothing ("open daily"); right after an amount it is a dose.
_DAILY = (
    r"(?:\b(?:daily|per\s+day|a\s+day|each\s+day|every\s+day|k[ei]l\s+yom|"
    r"bi?l\s*nhar|bi?l\s*yom)\b|باليوم|بالنهار|يوميا|كل\s+يوم)"
)
_EVERY_HOURS = (
    r"(?:\b(?:every|each)\s+\d+\s*(?:hours?|hrs?|h)\b|"
    r"\bk[ei]l\s+\d+\s*s[ae]3a(?:t)?\b|كل\s+\d+\s+ساع(?:ة|ات))"
)
_ADVICE_VERB = (
    r"(?:\byou\s+(?:should|can|could|may|must|need\s+to)\s+(?:take|use|try|stop|start|"
    r"increase|reduce|double|skip)\b|"
    r"\bi\s+(?:recommend|suggest|advise)\b|\b(?:try|take)\s+(?:it|them|one|two|\d+)\b|"
    r"\b(?:khod|khede|khedi|khdo|khdiya|est3mel|esta3mel|ista3mel|jarreb|jarrbe|w2ef|wa22ef)\b|"
    r"(?<!\w)(?:خذ|خذي|خدي|استعمل|استعملي|جرب|جربي)(?!\w)|توقف\s+عن)"
)
# The one sentence about "taking it" that is logistics: asking, or saying back, for how
# many days the client takes the medicine ("for how many days will you take it?", "you
# take it for 7 days, so the box of 24 tablets lasts"). Next to a strength or a box size
# it read as a dose (found on 2026-11-22). It is let through only when the sentence is
# about days and says nothing of how often, of hours or of food.
_ASKS_THE_DAYS = re.compile(
    rf"\b(?:you|you{_APOSTROPHE}ll|will\s+you|do\s+you|to)\s+take\s+(?:it|them)\b",
    re.IGNORECASE,
)
_ABOUT_DAYS = re.compile(r"\bdays?\b|\bhow\s+long\b|\blasts?\b", re.IGNORECASE)
_WITH_FOOD = (
    r"(?:\b(?:with|after|before)\s+(?:food|meals?|eating)\b|\bempty\s+stomach\b|"
    r"\b(?:abel|2abel|ba3d|ba3ed|ma3)\s+(?:l\s*|el\s*)?akel\b|"
    r"قبل\s+الأكل|بعد\s+الأكل|مع\s+الأكل|على\s+الريق)"
)
_SYMPTOM = (
    r"(?:pain|headache|migraine|fever|cough|flu|cold|infection|inflammation|blood\s+pressure|"
    r"pressure|diabetes|sugar|stomach|nausea|allerg(?:y|ies)|anxiety|insomnia|sleep|"
    r"waja3|wa2a3|sokhne|7arara|sa3le|rash7|da8et|daghet|da2et|sekkar|me3de|"
    r"وجع|ألم|صداع|حرارة|سعلة|رشح|التهاب|ضغط|سكري|معدة)"
)
_REFUSAL = (
    rf"(?:\bcan{_APOSTROPHE}t\b|\bcannot\b|\bcan\s+not\b|\bunable\b|\bnot\s+able\b|"
    rf"\bwon{_APOSTROPHE}t\b|\bma\s+(?:b2dar|fiye|fini|be2dar|b2der)\b|"
    r"لا\s+(?:أستطيع|يمكنني)|ما\s+(?:بقدر|فيني))"
)

# 1. A dose with how often: "500 mg twice a day", "2 tablets daily", "7abbten bil nhar".
DOSE_AND_FREQUENCY = re.compile(
    rf"{_SOME}.{{0,30}}?{_FREQUENCY}|{_FREQUENCY}.{{0,30}}?{_SOME}|{_SOME}.{{0,10}}?{_DAILY}",
    re.IGNORECASE,
)
# 2. "every 8 hours", "kel 8 se3at".
EVERY_HOURS = re.compile(_EVERY_HOURS, re.IGNORECASE)
# 3. Telling the client to take something, with an amount, a frequency or food.
ADVICE = re.compile(
    rf"{_ADVICE_VERB}.{{0,60}}?(?:{_SOME}|{_FREQUENCY}|{_EVERY_HOURS}|{_WITH_FOOD})",
    re.IGNORECASE,
)
_HOW_OFTEN_OR_FOOD = re.compile(
    rf"{_FREQUENCY}|{_DAILY}|{_EVERY_HOURS}|{_WITH_FOOD}", re.IGNORECASE
)
# 4. Claims about safety, interactions or side effects.
SAFETY_CLAIM = re.compile(
    rf"(?:\b(?:is|are|it{_APOSTROPHE}s|that{_APOSTROPHE}s)\s+"
    r"(?:safe|dangerous|harmful)\s+(?:to|for|with|during|in)\b|"
    # "Fine" and "ok" are also how plain things are said ("any day is fine for the pickup",
    # "'I don't know' is fine for the last two", "is that ok with you?", "it's fine to
    # answer any"). Only those plain objects are let through: fine for anyone, for a
    # symptom or for an organ, fine to take, and fine with another medicine stay claims.
    rf"\b(?:is|are|it{_APOSTROPHE}s|that{_APOSTROPHE}s)\s+(?:fine|ok|okay)\s+"
    r"(?:to\s+(?!me\b|us\b|you\b|say\b|answer\b|leave\b|skip\b|wait\b|come\b|pick\b|ask\b|"
    r"tell\b|write\b|choose\b|search\b|reply\b|go\b)|"
    r"with\s+(?!me\b|us\b|you\b|that\b|this\b|them\b|the\s+pharmac)|"
    r"for\s+(?!(?:the\s+)?(?:pickup|pick-up|days?|last|first|second|third|others?|rest|"
    r"search|card|pharmacy|trip|price|budget|moment|time)\b|those\b|these\b|that\b|this\b|"
    r"you\b|me\b|us\b|both\b|either\b|any\b|all\b|now\b|today\b|tomorrow\b)|"
    r"during\b|in\s+pregnan)|"
    r"\bno\s+(?:known\s+)?(?:interactions?|side\s+effects?)\b|"
    rf"\b(?:does\s*n{_APOSTROPHE}t|does\s+not|do\s+not|don{_APOSTROPHE}t|won{_APOSTROPHE}t)"
    r"\s+interact\b|"
    r"\binteracts?\s+with\b|\bside\s+effects?\s+(?:are|include|of)\b|\bcan\s+cause\b|"
    r"\bsafe\s+(?:in|during|for)\s+pregnan|\b(?:while|when)\s+(?:pregnant|breastfeeding)\b|"
    r"\bmafi\s+(?:mechkle|meshkle|mashkal)\s+(?:tekh[do]|ma3)|\bma\s+b[iy]dorr\b|"
    r"آمن\s+(?:لل|مع|خلال)|لا\s+يتعارض|آثار\s+جانبية\s+(?:هي|مثل)|للحامل)",
    re.IGNORECASE,
)
# 5. Saying a medicine is good for a symptom.
GOOD_FOR = re.compile(
    rf"(?:\b(?:is|are|it{_APOSTROPHE}s)\s+(?:good|great|effective|best|recommended|used)\s+"
    rf"(?:for|against)\s+(?:your\s+|the\s+|a\s+)?{_SYMPTOM}|"
    rf"\b(?:works?|helps?)\s+(?:for|against|with)\s+(?:your\s+|the\s+)?{_SYMPTOM}|"
    rf"\b(?:mni7|mnee7|mnih|b[iy]enfa3|b[iy]nfa3)\s+(?:la|lal|lel|l)\s*(?:l\s*|el\s*)?{_SYMPTOM}|"
    rf"(?:منيح|بينفع|مفيد)\s+(?:لل|ل)\s*{_SYMPTOM}|"
    rf"\bfor\s+(?:your\s+|the\s+|a\s+)?{_SYMPTOM}\b.{{0,40}}?"
    r"\b(?:try|take|use|i\s+recommend|i\s+suggest)\b)",
    re.IGNORECASE,
)
# 6. Saying another brand can replace the client's medicine. Whether it can is the
# pharmacist's to say (R-C10): the agent says where the brand is and "ask the pharmacist".
# "Ask the pharmacist if it suits you" is the wording we want, so "if" and "whether"
# right before are let through.
SUBSTITUTION = re.compile(
    r"(?:\b(?:take|use|have|get)\s+(?:it|this|that|them|one|\w+)\s+instead\b|"
    r"\b(?:just\s+as\s+good|works?\s+(?:just\s+)?the\s+same|(?:the\s+)?same\s+effect|"
    r"equally\s+effective|interchangeable|no\s+difference\s+between)\b|"
    r"(?<!\bif )(?<!whether )\b(?:it|this(?:\s+brand)?|that(?:\s+brand)?)\s+"
    r"(?:suits|will\s+suit|is\s+suitable\s+for|is\s+right\s+for)\s+you\b|"
    r"\b(?:fik|fiki|btefdar|bte2dar|bt2dar)\s+tekh[do]\w*\s+badal\w*|"
    r"\bnafs\s+(?:l\s*|el\s*)?(?:maf3oul|maf3ool|ta2sir|fa3aliyye)\b|"
    r"يمكنك\s+(?:أخذه|استعماله|استخدامه)\s+بدل|"
    r"(?:نفس|بنفس|بذات)\s+(?:المفعول|التأثير|الفعالية))",
    re.IGNORECASE,
)
_REFUSING = re.compile(_REFUSAL, re.IGNORECASE)
_SENTENCES = re.compile(r"[^.!?؟\n]+")
_CHECKS = (
    ("dose_and_frequency", DOSE_AND_FREQUENCY, False),
    ("every_hours", EVERY_HOURS, False),
    ("advice", ADVICE, False),
    ("safety_claim", SAFETY_CLAIM, True),
    ("good_for", GOOD_FOR, True),
    ("substitution", SUBSTITUTION, True),
)


def without_names(text: str, names: Iterable[str]) -> str:
    """The text with these product names taken out, before it is checked.

    The Ministry writes some products with a word that is also dosing shorthand ("… BID",
    "… TID"): naming such a product with its strength read as "a dose with how often", and
    a plain search answer was replaced by a refusal (found on 2026-11-22).
    """
    for name in sorted({name.strip() for name in names if name}, key=len, reverse=True):
        if len(name) >= 3:
            text = re.sub(re.escape(name), "the medicine", text, flags=re.IGNORECASE)
    return text


def clinical_reasons(text: str) -> list[str]:
    """Why this text reads as medical advice; empty when it doesn't."""
    reasons: list[str] = []
    for sentence in _SENTENCES.findall(text):
        refusing = bool(_REFUSING.search(sentence))
        asks_the_days = bool(
            _ASKS_THE_DAYS.search(sentence)
            and _ABOUT_DAYS.search(sentence)
            and not _HOW_OFTEN_OR_FOOD.search(sentence)
        )
        for name, pattern, skipped_when_refusing in _CHECKS:
            if skipped_when_refusing and refusing:
                continue
            if name == "advice" and asks_the_days:
                continue
            if name not in reasons and pattern.search(sentence):
                reasons.append(name)
    return reasons
