"""Trading-day arithmetic. All timestamps inside the bot are timezone-aware UTC."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(ts: datetime) -> datetime:
    """Reject naive datetimes: guessing a zone is how daily limits drift an hour."""
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"naive datetime {ts!r}; pass a timezone-aware value")
    return ts.astimezone(timezone.utc)


def trading_day(ts: datetime, reset_tz: ZoneInfo, reset_time: time) -> date:
    """The prop firm's trading day that ``ts`` belongs to.

    With a 17:00 New York reset (CME convention), Monday 18:00 NY belongs to
    Tuesday's session. With a 00:00 reset, the trading day is the calendar day.
    """
    local = ensure_utc(ts).astimezone(reset_tz)
    if reset_time == time(0, 0):
        return local.date()
    if local.time() >= reset_time:
        return local.date() + timedelta(days=1)
    return local.date()


def next_reset(ts: datetime, reset_tz: ZoneInfo, reset_time: time) -> datetime:
    """The first reset boundary strictly after ``ts``, in UTC."""
    local = ensure_utc(ts).astimezone(reset_tz)
    candidate = datetime.combine(local.date(), reset_time, tzinfo=reset_tz)
    if candidate <= local:
        candidate = datetime.combine(local.date() + timedelta(days=1), reset_time, tzinfo=reset_tz)
    return candidate.astimezone(timezone.utc)
