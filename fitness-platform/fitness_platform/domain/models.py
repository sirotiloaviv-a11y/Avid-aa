"""Domain objects.

Repositories return these, not raw ``sqlite3.Row`` objects, so nothing above the
db package has to know a column name — or accidentally render one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from ..db.json_fields import loads
from .gender import ContentScope, GenderPath
from .roles import Role
from .subscription import SubscriptionStatus


def _row(row: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(row) if row is not None else {}


@dataclass
class User:
    id: int
    email: str
    name: str
    role: Role
    gender_path: GenderPath | None
    onboarding_completed: bool
    status: str
    created_at: str = ""
    last_active_at: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | None) -> "User | None":
        data = _row(row)
        if not data:
            return None
        return cls(
            id=int(data["id"]),
            email=data["email"],
            name=data.get("name") or "",
            role=Role.parse(data.get("role")),
            gender_path=GenderPath.parse(data.get("gender_path")),
            onboarding_completed=bool(data.get("onboarding_completed")),
            status=data.get("status") or "active",
            created_at=data.get("created_at") or "",
            last_active_at=data.get("last_active_at") or "",
        )

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    @property
    def first_name(self) -> str:
        return (self.name or self.email.split("@")[0]).split(" ")[0]

    @property
    def initials(self) -> str:
        parts = [part for part in (self.name or self.email).split(" ") if part]
        return "".join(part[0] for part in parts[:2]).upper() or "?"


@dataclass
class Profile:
    user_id: int
    display_name: str = ""
    avatar_url: str = ""
    birth_year: int | None = None
    height_cm: int | None = None
    weight_kg: float | None = None
    experience_level: str = "beginner"
    weekly_frequency: int = 3
    session_minutes: int = 30
    equipment: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    dietary_tags: list[str] = field(default_factory=list)
    allergies: list[str] = field(default_factory=list)
    disliked_foods: list[str] = field(default_factory=list)
    meals_per_day: int = 3
    preferred_days: list[str] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | None) -> "Profile | None":
        data = _row(row)
        if not data:
            return None
        return cls(
            user_id=int(data["user_id"]),
            display_name=data.get("display_name") or "",
            avatar_url=data.get("avatar_url") or "",
            birth_year=data.get("birth_year"),
            height_cm=data.get("height_cm"),
            weight_kg=data.get("weight_kg"),
            experience_level=data.get("experience_level") or "beginner",
            weekly_frequency=int(data.get("weekly_frequency") or 3),
            session_minutes=int(data.get("session_minutes") or 30),
            equipment=loads(data.get("equipment")),
            goals=loads(data.get("goals")),
            dietary_tags=loads(data.get("dietary_tags")),
            allergies=loads(data.get("allergies")),
            disliked_foods=loads(data.get("disliked_foods")),
            meals_per_day=int(data.get("meals_per_day") or 3),
            preferred_days=loads(data.get("preferred_days")),
        )

    @classmethod
    def empty(cls, user_id: int) -> "Profile":
        return cls(user_id=user_id)


@dataclass
class Coach:
    id: int
    name: str
    gender_path: ContentScope
    photo_url: str = ""
    bio: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | None) -> "Coach | None":
        data = _row(row)
        if not data:
            return None
        return cls(
            id=int(data["id"]),
            name=data.get("name") or "",
            gender_path=ContentScope.parse(data.get("gender_path")) or ContentScope.ALL,
            photo_url=data.get("photo_url") or "",
            bio=data.get("bio") or "",
        )


@dataclass
class Video:
    id: int
    title: str
    description: str
    thumbnail_url: str
    video_url: str
    duration: int
    difficulty: str
    category: str
    gender_path: ContentScope
    coach_id: int | None
    equipment: list[str]
    tags: list[str]
    published: bool
    coach_name: str = ""
    progress_status: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | None) -> "Video | None":
        data = _row(row)
        if not data:
            return None
        return cls(
            id=int(data["id"]),
            title=data.get("title") or "",
            description=data.get("description") or "",
            thumbnail_url=data.get("thumbnail_url") or "",
            video_url=data.get("video_url") or "",
            duration=int(data.get("duration") or 0),
            difficulty=data.get("difficulty") or "beginner",
            category=data.get("category") or "full_body",
            gender_path=ContentScope.parse(data.get("gender_path")) or ContentScope.ALL,
            coach_id=data.get("coach_id"),
            equipment=loads(data.get("equipment")),
            tags=loads(data.get("tags")),
            published=bool(data.get("published")),
            coach_name=data.get("coach_name") or "",
            progress_status=data.get("progress_status") or "",
        )

    @property
    def completed(self) -> bool:
        return self.progress_status == "completed"


@dataclass
class Recipe:
    id: int
    name: str
    description: str
    ingredients: list[dict[str, Any]]
    instructions: list[str]
    image_url: str
    tags: list[str]
    meal_type: str
    dietary_tags: list[str]
    allergens: list[str]
    gender_path: ContentScope
    prep_minutes: int
    approved: bool

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | None) -> "Recipe | None":
        data = _row(row)
        if not data:
            return None
        return cls(
            id=int(data["id"]),
            name=data.get("name") or "",
            description=data.get("description") or "",
            ingredients=loads(data.get("ingredients")),
            instructions=loads(data.get("instructions")),
            image_url=data.get("image_url") or "",
            tags=loads(data.get("tags")),
            meal_type=data.get("meal_type") or "lunch",
            dietary_tags=loads(data.get("dietary_tags")),
            allergens=loads(data.get("allergens")),
            gender_path=ContentScope.parse(data.get("gender_path")) or ContentScope.ALL,
            prep_minutes=int(data.get("prep_minutes") or 0),
            approved=bool(data.get("approved")),
        )


@dataclass
class ProgramDay:
    id: int
    program_id: int
    day_number: int
    title: str
    focus: str
    is_rest: bool
    videos: list[Video] = field(default_factory=list)


@dataclass
class Program:
    id: int
    name: str
    description: str
    gender_path: ContentScope
    duration_weeks: int
    difficulty: str
    goal_tags: list[str]
    equipment: list[str]
    cover_url: str
    published: bool
    days: list[ProgramDay] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | None) -> "Program | None":
        data = _row(row)
        if not data:
            return None
        return cls(
            id=int(data["id"]),
            name=data.get("name") or "",
            description=data.get("description") or "",
            gender_path=ContentScope.parse(data.get("gender_path")) or ContentScope.ALL,
            duration_weeks=int(data.get("duration_weeks") or 4),
            difficulty=data.get("difficulty") or "beginner",
            goal_tags=loads(data.get("goal_tags")),
            equipment=loads(data.get("equipment")),
            cover_url=data.get("cover_url") or "",
            published=bool(data.get("published")),
        )


@dataclass
class Subscription:
    id: int
    user_id: int
    plan_code: str
    status: SubscriptionStatus
    provider: str
    provider_ref: str
    amount_cents: int
    currency: str
    current_period_end: str | None
    created_at: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | None) -> "Subscription | None":
        data = _row(row)
        if not data:
            return None
        return cls(
            id=int(data["id"]),
            user_id=int(data["user_id"]),
            plan_code=data.get("plan_code") or "",
            status=SubscriptionStatus.parse(data.get("status")),
            provider=data.get("provider") or "mock",
            provider_ref=data.get("provider_ref") or "",
            amount_cents=int(data.get("amount_cents") or 0),
            currency=data.get("currency") or "ILS",
            current_period_end=data.get("current_period_end"),
            created_at=data.get("created_at") or "",
        )

    @property
    def is_active(self) -> bool:
        if not self.status.grants_access:
            return False
        if self.current_period_end:
            try:
                end = datetime.fromisoformat(self.current_period_end)
            except ValueError:
                return True
            return end >= datetime.utcnow() - timedelta(seconds=1)
        return True

    @property
    def days_remaining(self) -> int:
        if not self.current_period_end:
            return 0
        try:
            end = datetime.fromisoformat(self.current_period_end)
        except ValueError:
            return 0
        return max(0, (end.date() - date.today()).days)


@dataclass
class AuthContext:
    """Everything a route needs to make an access decision."""

    user: User
    profile: Profile
    subscription: Subscription | None

    @property
    def gender_path(self) -> GenderPath | None:
        return self.user.gender_path

    @property
    def has_active_subscription(self) -> bool:
        return bool(self.subscription and self.subscription.is_active)
