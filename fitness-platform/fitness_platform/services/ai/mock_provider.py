"""The development provider (50).

It is honest about being a mock: answers are assembled from the same approved
content the real provider would be handed, so the product behaves correctly
without a vendor key, and nothing on screen pretends to be a model response
that never happened.
"""

from __future__ import annotations

import time

from .provider import AIProvider, AIRequest, AIResponse, timed

_GREETING = "אני כאן כדי לעזור לך למצוא את הדרך בתוכן שלנו."


class MockAIProvider(AIProvider):
    name = "mock"

    @property
    def is_mock(self) -> bool:
        return True

    def complete(self, request: AIRequest) -> AIResponse:
        start = time.monotonic()
        question = request.messages[-1].content.strip() if request.messages else ""
        blocks = [block for block in request.context_blocks if block.strip()]

        lines: list[str] = []
        if not question:
            lines.append(_GREETING)
        else:
            lines.append(self._intent_line(question))

        if blocks:
            lines.append("")
            lines.append("מתוך התוכן שמתאים לך:")
            lines.extend(blocks[:3])
        else:
            lines.append("")
            lines.append("לא מצאתי פריט מתאים בספרייה שלך כרגע — כדאי לנסות ניסוח אחר או לפנות לתמיכה.")

        lines.append("")
        lines.append("שימו לב: אני עוזר לנווט בתוכן של הפלטפורמה ולא נותן ייעוץ רפואי.")
        text = "\n".join(lines)
        return AIResponse(
            text=text,
            provider=self.name,
            tokens=len(text.split()),
            latency_ms=timed(start),
        )

    @staticmethod
    def _intent_line(question: str) -> str:
        lowered = question.lower()
        if any(word in question for word in ("ארוח", "אוכל", "תפריט", "מתכון")):
            return "בדקתי את התפריט המאושר שמתאים להעדפות שלך."
        if any(word in question for word in ("אימון", "תרגיל", "סרטון", "תוכנית")):
            return "הנה האימונים שמתאימים לרמה, לציוד ולזמן שהגדרת."
        if any(word in question for word in ("ביטול", "מנוי", "חיוב", "תשלום")):
            return "ניהול המנוי נמצא בהגדרות החשבון, תחת ״המנוי שלי״."
        return "הנה מה שמצאתי עבורך בתוכן של המסלול שלך."
