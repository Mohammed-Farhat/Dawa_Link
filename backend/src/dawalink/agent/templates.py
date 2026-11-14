"""Text written by us, never by the model (docs/07 §7.3).

These are sent when the model's own reply can't be used: it gave medical advice twice,
it couldn't be reached, or the client's daily budget is used up. Each exists in English,
Arabic and Arabizi, and the client's language decides which one is sent.
"""

from enum import StrEnum
from typing import Literal

Language = Literal["english", "arabic", "arabizi"]


class Fixed(StrEnum):
    CLINICAL_REFUSAL = "clinical_refusal"
    NEUTRAL = "neutral"  # with this turn's cards under it
    TRY_AGAIN = "try_again"  # when there is no card to show
    EMERGENCY = "emergency"
    UNAVAILABLE = "unavailable"
    BUDGET_REACHED = "budget_reached"
    HANDED_TO_A_PERSON = "handed_to_a_person"


_TEXT: dict[Fixed, dict[Language, str]] = {
    Fixed.CLINICAL_REFUSAL: {
        "english": (
            "I can't advise on medicines or doses; a pharmacist or doctor can. "
            "Do you want me to keep searching?"
        ),
        "arabic": (
            "لا أستطيع أن أنصح بالأدوية أو الجرعات؛ الصيدلي أو الطبيب يستطيع ذلك. "
            "هل تريد أن أتابع البحث؟"
        ),
        "arabizi": (
            "Ma b2dar ensa7 bil adwiye aw l jar3at; l saydale aw l 7akim byi2dar. "
            "Baddak kammel l ba7s?"
        ),
    },
    Fixed.NEUTRAL: {
        "english": "Sorry, I couldn't answer that. Here's what I found:",
        "arabic": "عذراً، لم أستطع الإجابة على ذلك. هذا ما وجدته:",
        "arabizi": "Sorry, ma 2dert jeweb 3a hal shi. Hayda li l2ayto:",
    },
    Fixed.TRY_AGAIN: {
        "english": "Sorry, I couldn't answer that. Could you say it another way?",
        "arabic": "عذراً، لم أستطع الإجابة على ذلك. هل يمكنك أن تعيد صياغة طلبك؟",
        "arabizi": "Sorry, ma 2dert jeweb 3a hal shi. Fik t2oula b tari2a tenye?",
    },
    Fixed.EMERGENCY: {
        "english": (
            "New stock goes to whoever asked first, and nobody can change that order. "
            "If this is a medical emergency, please contact a doctor or emergency services "
            "now. A person from DawaLink can also help you."
        ),
        "arabic": (
            "المخزون الجديد يذهب لمن طلب أولاً، ولا أحد يستطيع تغيير هذا الترتيب. "
            "إذا كانت حالة طبية طارئة، اتصل بطبيب أو بالطوارئ الآن. "
            "يمكن أيضاً لشخص من فريق دوالينك أن يساعدك."
        ),
        "arabizi": (
            "L stock l jdid byrou7 la yalli talab awwal, w ma 7ada byi2dar yghayyer hal tartib. "
            "Eza 7ale tebbiye tar2a, e7ke ma3 7akim aw l tawari2 hala2. "
            "Kamen fi 7ada men DawaLink byi2dar yse3dak."
        ),
    },
    Fixed.UNAVAILABLE: {
        "english": "The assistant isn't available right now. You can still use Search.",
        "arabic": "المساعد غير متاح الآن. ما زال بإمكانك استعمال البحث.",
        "arabizi": "L assistant mech meweujoud hala2. Fik test3mel l Search.",
    },
    Fixed.BUDGET_REACHED: {
        "english": "The assistant is paused for today. You can still use Search.",
        "arabic": "المساعد متوقف لهذا اليوم. ما زال بإمكانك استعمال البحث.",
        "arabizi": "L assistant wa22af la lyom. Fik test3mel l Search.",
    },
    Fixed.HANDED_TO_A_PERSON: {
        "english": "A person from DawaLink will look at this.",
        "arabic": "سينظر شخص من فريق دوالينك في هذا الطلب.",
        "arabizi": "7ada men DawaLink ra7 yshouf hal shi.",
    },
}


def fixed(which: Fixed, language: str | None) -> str:
    """The template in the client's language; English when it isn't known."""
    by_language = _TEXT[which]
    if language == "arabic":
        return by_language["arabic"]
    if language == "arabizi":
        return by_language["arabizi"]
    return by_language["english"]
