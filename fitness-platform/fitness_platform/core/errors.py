"""Application errors.

Routes raise these; the WSGI layer turns them into a friendly page or a JSON
envelope (39). Stack traces never reach the browser.
"""

from __future__ import annotations


class AppError(Exception):
    status = 500
    code = "internal_error"
    message = "משהו השתבש אצלנו. נסו שוב בעוד רגע."

    def __init__(self, message: str | None = None, *, code: str | None = None):
        super().__init__(message or self.message)
        if message:
            self.message = message
        if code:
            self.code = code


class BadRequest(AppError):
    status = 400
    code = "bad_request"
    message = "הבקשה לא תקינה."


class ValidationError(BadRequest):
    code = "validation_error"
    message = "יש שדות שצריך לתקן."

    def __init__(self, errors: dict[str, str] | None = None, message: str | None = None):
        super().__init__(message)
        self.errors = errors or {}


class Unauthorized(AppError):
    status = 401
    code = "unauthorized"
    message = "צריך להתחבר כדי להמשיך."


class Forbidden(AppError):
    status = 403
    code = "forbidden"
    message = "אין לך הרשאה לגשת לאזור הזה."


class NotFound(AppError):
    status = 404
    code = "not_found"
    message = "לא מצאנו את מה שחיפשת."


class MethodNotAllowed(AppError):
    status = 405
    code = "method_not_allowed"
    message = "הפעולה הזו לא נתמכת בכתובת הזו."


class Conflict(AppError):
    status = 409
    code = "conflict"
    message = "הפעולה מתנגשת עם מצב קיים."


class RateLimited(AppError):
    status = 429
    code = "rate_limited"
    message = "יותר מדי בקשות. נסו שוב בעוד דקה."


class PaymentRequired(Forbidden):
    code = "payment_required"
    message = "המנוי שלך לא פעיל."
