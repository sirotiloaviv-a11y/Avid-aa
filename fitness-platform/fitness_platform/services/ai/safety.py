"""Guard rails around the assistant (18, 21, 28).

Two jobs: keep the member from being answered as if this were a clinic, and
keep prompt text from steering the assistant outside the product. Both run on
the server; neither is a UI affordance the client can skip.
"""

from __future__ import annotations

import re

MEDICAL_PATTERNS = (
    r"כאב(ים)?\s+(חד|חזק|בחזה)",
    r"פציע(ה|ות)",
    r"תרופ(ה|ות)",
    r"הריון",
    r"אבחנ(ה|ות)",
    r"סוכרת|לחץ\s*דם|לב\b",
    r"דיאט(ה|ת)\s*(רפואית|קלורית מדויקת)",
)

INJECTION_PATTERNS = (
    r"התעלם\s+מ?ה?הוראות",
    r"ignore\s+(all\s+)?(of\s+)?(the\s+)?(previous|prior|above|earlier\s+)?\s*instructions",
    r"system prompt",
    r"אתה\s+עכשיו\s+",
    r"act as (an? )?(admin|administrator|root)",
    r"reveal|הדלף|תחשוף",
)

MEDICAL_REPLY = (
    "אני לא יכול לתת ייעוץ רפואי או להתייחס לתסמינים. "
    "אם משהו מטריד אתכם — כדאי להתייעץ עם רופא או פיזיותרפיסט. "
    "אני כאן כדי לעזור עם האימונים, התפריט והשימוש במערכת."
)

OUT_OF_SCOPE_REPLY = (
    "אני עוזר רק בנושאים של האימונים, התפריט והתוכן בפלטפורמה. "
    "אפשר לשאול אותי למשל איזה אימון מתאים היום או איך מחליפים ארוחה."
)

MAX_QUESTION_LENGTH = 800


def check_question(question: str) -> tuple[bool, str]:
    """Returns ``(allowed, replacement_reply)``."""
    text = (question or "").strip()
    if not text:
        return False, "לא קיבלתי שאלה. מה תרצו לדעת?"
    if len(text) > MAX_QUESTION_LENGTH:
        return False, "השאלה ארוכה מדי. אפשר לנסח אותה קצר יותר?"
    lowered = text.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, lowered) or re.search(pattern, text):
            return False, OUT_OF_SCOPE_REPLY
    for pattern in MEDICAL_PATTERNS:
        if re.search(pattern, text):
            return False, MEDICAL_REPLY
    return True, ""


def sanitize_answer(answer: str) -> str:
    """Trim anything that reads like a medical instruction out of a reply."""
    text = (answer or "").strip()
    if not text:
        return "לא הצלחתי לנסח תשובה כרגע. אפשר לנסות שוב בעוד רגע."
    banned = ("מומלץ ליטול", "מינון", "טיפול תרופתי")
    for phrase in banned:
        if phrase in text:
            return MEDICAL_REPLY
    return text
