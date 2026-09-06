"""Questionnaire orchestration (7, 9, 11)."""

from __future__ import annotations

from dataclasses import dataclass

from ..db.repositories import onboarding as onboarding_repo, users as users_repo
from ..domain.models import User
from ..domain.onboarding import Step, profile_updates, step_count, steps_for, validate_step
from . import analytics


@dataclass
class StepView:
    step: Step
    index: int
    total: int
    answers: dict
    errors: dict

    @property
    def percent(self) -> int:
        return round(100 * self.index / self.total)

    @property
    def is_last(self) -> bool:
        return self.index == self.total - 1


def resume_index(user: User) -> int:
    """Where the member left off (11)."""
    progress = onboarding_repo.get_progress(user.id)
    total = step_count(user.gender_path) if user.gender_path else 0
    current = int(progress.get("current_step") or 0)
    return max(0, min(current, max(0, total - 1)))


def load_step(user: User, index: int) -> StepView | None:
    path = user.gender_path
    if path is None:
        return None
    steps = steps_for(path)
    if not 0 <= index < len(steps):
        return None
    answers = onboarding_repo.get_answers(user.id)
    if index == 0 and not answers:
        analytics.track(analytics.ONBOARDING_STARTED, user_id=user.id, gender_path=path.value)
    return StepView(step=steps[index], index=index, total=len(steps), answers=answers, errors={})


def submit_step(user: User, index: int, raw: dict[str, list[str]]) -> tuple[bool, StepView | None]:
    """Validate and persist one step. Returns ``(ok, view_with_errors)``."""
    path = user.gender_path
    if path is None:
        return False, None
    steps = steps_for(path)
    if not 0 <= index < len(steps):
        return False, None
    step = steps[index]

    cleaned, errors = validate_step(step, raw)
    if errors:
        view = StepView(step=step, index=index, total=len(steps), answers=onboarding_repo.get_answers(user.id), errors=errors)
        # Keep what the member typed so a validation error never wipes the form.
        view.answers.update({key: values[0] if len(values) == 1 else values for key, values in raw.items()})
        return False, view

    onboarding_repo.save_answers(user.id, step.key, cleaned)
    users_repo.update_profile(user.id, profile_updates(path, cleaned))
    if cleaned.get("display_name"):
        users_repo.update_profile_name(user.id, str(cleaned["display_name"]))
    onboarding_repo.set_progress(user.id, min(index + 1, len(steps) - 1), len(steps))
    return True, None


def complete(user: User) -> None:
    onboarding_repo.mark_completed(user.id)
    users_repo.mark_onboarding_complete(user.id)
    analytics.track(
        analytics.ONBOARDING_COMPLETED,
        user_id=user.id,
        gender_path=user.gender_path.value if user.gender_path else None,
    )


def is_complete(user: User) -> bool:
    return bool(user.onboarding_completed)
