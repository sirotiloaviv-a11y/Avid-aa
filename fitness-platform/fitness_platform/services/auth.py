"""Sign-up, sign-in and session lifecycle (3, 11, 34)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.errors import Conflict, RateLimited, Unauthorized, ValidationError
from ..config import get_settings
from ..db.repositories import billing, users as users_repo
from ..domain.gender import GenderPath
from ..domain.models import AuthContext, User
from ..domain.roles import Role
from . import analytics
from .security import hash_password, limiter, needs_rehash, new_token, verify_password

SESSION_COOKIE = "fp_session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")
MIN_PASSWORD_LENGTH = 8


@dataclass
class SessionInfo:
    session_id: str
    csrf_token: str
    user: User


def validate_signup(email: str, password: str, name: str) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not EMAIL_RE.match(email.strip().lower()):
        errors["email"] = "כתובת אימייל לא תקינה"
    if len(password) < MIN_PASSWORD_LENGTH:
        errors["password"] = f"הסיסמה צריכה להכיל לפחות {MIN_PASSWORD_LENGTH} תווים"
    elif password.isdigit() or password.isalpha():
        errors["password"] = "כדאי לשלב אותיות ומספרים"
    if len(name.strip()) < 2:
        errors["name"] = "צריך שם מלא"
    return errors


def register(
    email: str,
    password: str,
    name: str,
    gender_path: GenderPath | None,
    *,
    role: Role = Role.USER,
) -> User:
    email = email.strip().lower()
    errors = validate_signup(email, password, name)
    if errors:
        raise ValidationError(errors)
    if users_repo.email_exists(email):
        raise Conflict("כבר קיים חשבון עם האימייל הזה. אפשר להתחבר.")
    user_id = users_repo.create_user(
        email, hash_password(password), name=name.strip(), gender_path=gender_path, role=role
    )
    user = users_repo.get_user(user_id)
    assert user is not None
    analytics.track(
        "signup", user_id=user.id, gender_path=gender_path.value if gender_path else None
    )
    return user


def authenticate(email: str, password: str, *, ip_address: str = "") -> User:
    """Verify credentials.

    Failures are rate limited per IP *and* per email so neither a single client
    nor a distributed attempt on one account runs unbounded.
    """
    settings = get_settings()
    email = email.strip().lower()
    for key in (f"login:ip:{ip_address}", f"login:email:{email}"):
        if not limiter.check(key, settings.auth_rate_limit_per_minute):
            raise RateLimited("יותר מדי ניסיונות התחברות. נסו שוב בעוד דקה.")

    user = users_repo.get_user_by_email(email)
    stored = users_repo.get_password_hash(user.id) if user else ""
    # Always run a verification so a missing account and a wrong password take
    # the same time.
    ok = verify_password(password, stored or "$".join(["pbkdf2_sha256", "1", "00", "00"]))
    if not user or not ok:
        raise Unauthorized("האימייל או הסיסמה אינם נכונים.")
    if user.status != "active":
        raise Unauthorized("החשבון אינו פעיל. פנו לתמיכה.")
    if needs_rehash(stored):
        users_repo.update_password(user.id, hash_password(password))
    return user


def start_session(user: User, *, user_agent: str = "", ip_address: str = "") -> SessionInfo:
    settings = get_settings()
    session_id = new_token(32)
    csrf_token = new_token(24)
    users_repo.create_session(
        session_id,
        user.id,
        csrf_token,
        settings.session_ttl_seconds,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    users_repo.touch_last_active(user.id)
    return SessionInfo(session_id, csrf_token, user)


def end_session(session_id: str) -> None:
    if session_id:
        users_repo.delete_session(session_id)


def load_context(session_id: str) -> AuthContext | None:
    """Resolve a session cookie into the full authorisation context.

    Everything downstream — route guards, API handlers, the AI coach — reads the
    user's path and subscription from here and never from the request (2).
    """
    if not session_id:
        return None
    session = users_repo.get_session(session_id)
    if not session:
        return None
    user = users_repo.get_user(int(session["user_id"]))
    if not user or user.status != "active":
        return None
    profile = users_repo.get_profile(user.id)
    subscription = billing.latest_subscription(user.id)
    return AuthContext(user=user, profile=profile, subscription=subscription)


def session_csrf(session_id: str) -> str:
    session = users_repo.get_session(session_id)
    return session["csrf_token"] if session else ""


def change_password(user: User, current_password: str, new_password: str) -> None:
    stored = users_repo.get_password_hash(user.id)
    if not verify_password(current_password, stored):
        raise ValidationError({"current_password": "הסיסמה הנוכחית לא נכונה"})
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise ValidationError({"new_password": f"לפחות {MIN_PASSWORD_LENGTH} תווים"})
    users_repo.update_password(user.id, hash_password(new_password))
    users_repo.delete_user_sessions(user.id)
