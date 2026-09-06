"""The onboarding questionnaire (7, 8).

Questions are declared as data, not as markup, so the same definition drives
rendering, server-side validation and the mapping into the profile. Adding a
question is a one-line change here and nothing else.

Scope note: this is a preferences questionnaire. It asks nothing diagnostic and
produces no medical claim — the answers only steer which approved content the
rules engine picks (8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .gender import GenderPath

QuestionType = str  # "single" | "multi" | "number" | "text"


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    hint: str = ""
    icon: str = ""


@dataclass(frozen=True)
class Question:
    key: str
    label: str
    type: QuestionType
    options: tuple[Option, ...] = ()
    required: bool = True
    help_text: str = ""
    placeholder: str = ""
    min_value: int | None = None
    max_value: int | None = None
    max_choices: int | None = None
    profile_field: str = ""

    def option_values(self) -> set[str]:
        return {option.value for option in self.options}


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    subtitle: str
    questions: tuple[Question, ...]


def _basic_step(path: GenderPath) -> Step:
    you = "את" if path is GenderPath.FEMALE else "אתה"
    return Step(
        key="basics",
        title="קצת עלייך" if path is GenderPath.FEMALE else "קצת עליך",
        subtitle=f"כמה פרטים בסיסיים כדי שנדע איפה {you} מתחיל" + ("ה" if path is GenderPath.FEMALE else ""),
        questions=(
            Question(
                key="display_name",
                label="איך לקרוא לך?",
                type="text",
                placeholder="השם הפרטי",
                profile_field="display_name",
            ),
            Question(
                key="birth_year",
                label="שנת לידה",
                type="number",
                min_value=1930,
                max_value=2015,
                profile_field="birth_year",
                help_text="משמש רק להתאמת עצימות האימונים.",
            ),
            Question(
                key="height_cm",
                label="גובה (ס״מ)",
                type="number",
                min_value=120,
                max_value=230,
                required=False,
                profile_field="height_cm",
            ),
            Question(
                key="weight_kg",
                label="משקל נוכחי (ק״ג)",
                type="number",
                min_value=30,
                max_value=250,
                required=False,
                profile_field="weight_kg",
                help_text="אפשר לדלג ולעדכן בהמשך במעקב ההתקדמות.",
            ),
        ),
    )


def _experience_step(path: GenderPath) -> Step:
    return Step(
        key="experience",
        title="ניסיון באימונים",
        subtitle="כדי שנתחיל ברמה הנכונה",
        questions=(
            Question(
                key="experience_level",
                label="מה הרמה שלך היום?",
                type="single",
                profile_field="experience_level",
                options=(
                    Option("beginner", "מתחילה" if path is GenderPath.FEMALE else "מתחיל",
                           "פחות מ‑6 חודשי אימון רציף"),
                    Option("intermediate", "בינונית" if path is GenderPath.FEMALE else "בינוני",
                           "מתאמנ" + ("ת" if path is GenderPath.FEMALE else "") + " באופן קבוע"),
                    Option("advanced", "מתקדמת" if path is GenderPath.FEMALE else "מתקדם",
                           "שנתיים ומעלה של אימון עקבי"),
                ),
            ),
            Question(
                key="weekly_frequency",
                label="כמה אימונים בשבוע מתאימים לך?",
                type="single",
                profile_field="weekly_frequency",
                options=(
                    Option("2", "2 אימונים"),
                    Option("3", "3 אימונים"),
                    Option("4", "4 אימונים"),
                    Option("5", "5 אימונים ומעלה"),
                ),
            ),
            Question(
                key="session_minutes",
                label="כמה זמן יש לך לאימון?",
                type="single",
                profile_field="session_minutes",
                options=(
                    Option("20", "20 דקות"),
                    Option("30", "30 דקות"),
                    Option("45", "45 דקות"),
                    Option("60", "שעה"),
                ),
            ),
        ),
    )


def _equipment_step(path: GenderPath) -> Step:
    common = (
        Option("none", "בלי ציוד", "משקל גוף בלבד"),
        Option("mat", "מזרן"),
        Option("dumbbells", "משקולות יד"),
        Option("bands", "גומיות התנגדות"),
        Option("kettlebell", "קטלבל"),
        Option("gym", "מנוי לחדר כושר"),
    )
    extra = (
        (Option("pilates_ring", "טבעת פילאטיס"),)
        if path is GenderPath.FEMALE
        else (Option("barbell", "מוט ומשקולות"), Option("pullup_bar", "מתח ביתי"))
    )
    return Step(
        key="equipment",
        title="ציוד זמין",
        subtitle="נבנה את התוכנית סביב מה שיש לך",
        questions=(
            Question(
                key="equipment",
                label="מה זמין לך לאימון?",
                type="multi",
                profile_field="equipment",
                options=common + extra,
            ),
        ),
    )


def _goals_step(path: GenderPath) -> Step:
    if path is GenderPath.FEMALE:
        options = (
            Option("tone", "חיטוב וחיזוק"),
            Option("strength", "כוח וחיזוק שרירים"),
            Option("weight", "עלייה בכושר וירידה במשקל"),
            Option("posture", "יציבה וגמישות"),
            Option("energy", "יותר אנרגיה ביום‑יום"),
            Option("routine", "לבנות שגרה קבועה"),
        )
    else:
        options = (
            Option("muscle", "עלייה במסה"),
            Option("strength", "כוח ועוצמה"),
            Option("cut", "חיטוב והורדת אחוזי שומן"),
            Option("endurance", "סיבולת וכושר"),
            Option("mobility", "ניידות ומניעת פציעות"),
            Option("routine", "לבנות שגרה קבועה"),
        )
    return Step(
        key="goals",
        title="המטרות שלך",
        subtitle="אפשר לבחור עד שלוש",
        questions=(
            Question(
                key="goals",
                label="מה הכי חשוב לך להשיג?",
                type="multi",
                max_choices=3,
                profile_field="goals",
                options=options,
            ),
            Question(
                key="workout_style",
                label="איזה סגנון אימון מדבר אליך?",
                type="multi",
                required=False,
                options=(
                    Option("strength", "כוח והתנגדות"),
                    Option("hiit", "אינטרוולים ושריפה"),
                    Option("pilates", "פילאטיס ומתיחות"),
                    Option("mobility", "ניידות וקור"),
                    Option("cardio", "קרדיו"),
                ),
            ),
        ),
    )


def _food_step(path: GenderPath) -> Step:
    return Step(
        key="food",
        title="העדפות אוכל",
        subtitle="התפריט ייבנה ממתכונים מאושרים בלבד",
        questions=(
            Question(
                key="dietary_tags",
                label="יש סגנון תזונה שמתאים לך?",
                type="multi",
                required=False,
                profile_field="dietary_tags",
                options=(
                    Option("vegetarian", "צמחוני"),
                    Option("vegan", "טבעוני"),
                    Option("gluten_free", "ללא גלוטן"),
                    Option("dairy_free", "ללא מוצרי חלב"),
                    Option("high_protein", "עתיר חלבון"),
                    Option("kosher", "כשר"),
                ),
            ),
            Question(
                key="allergies",
                label="רגישויות או מרכיבים שאסור לכלול",
                type="multi",
                required=False,
                profile_field="allergies",
                help_text="נשמח לדעת כדי לא להציע מתכון שלא מתאים. זו אינה התייעצות רפואית.",
                options=(
                    Option("nuts", "אגוזים"),
                    Option("peanuts", "בוטנים"),
                    Option("dairy", "חלב"),
                    Option("eggs", "ביצים"),
                    Option("gluten", "גלוטן"),
                    Option("fish", "דגים"),
                    Option("soy", "סויה"),
                    Option("sesame", "שומשום"),
                ),
            ),
            Question(
                key="meals_per_day",
                label="כמה ארוחות ביום מתאימות לך?",
                type="single",
                profile_field="meals_per_day",
                options=(
                    Option("3", "3 ארוחות"),
                    Option("4", "3 ארוחות + נשנוש"),
                    Option("5", "5 ארוחות קטנות"),
                ),
            ),
            Question(
                key="disliked_foods",
                label="משהו שפשוט לא בא לך לאכול?",
                type="text",
                required=False,
                placeholder="לדוגמה: חציל, טופו",
                profile_field="disliked_foods",
            ),
        ),
    )


def _schedule_step(path: GenderPath) -> Step:
    return Step(
        key="schedule",
        title="מתי מתאים לך להתאמן",
        subtitle="נסדר את השבוע סביב הזמנים שלך",
        questions=(
            Question(
                key="preferred_days",
                label="באילו ימים?",
                type="multi",
                profile_field="preferred_days",
                options=(
                    Option("sun", "ראשון"),
                    Option("mon", "שני"),
                    Option("tue", "שלישי"),
                    Option("wed", "רביעי"),
                    Option("thu", "חמישי"),
                    Option("fri", "שישי"),
                    Option("sat", "שבת"),
                ),
            ),
            Question(
                key="preferred_time",
                label="באיזו שעה ביום?",
                type="single",
                required=False,
                options=(
                    Option("morning", "בוקר"),
                    Option("noon", "צהריים"),
                    Option("evening", "ערב"),
                    Option("flexible", "גמיש"),
                ),
            ),
        ),
    )


def steps_for(path: GenderPath) -> tuple[Step, ...]:
    return (
        _basic_step(path),
        _experience_step(path),
        _equipment_step(path),
        _goals_step(path),
        _food_step(path),
        _schedule_step(path),
    )


def step_count(path: GenderPath) -> int:
    return len(steps_for(path))


def get_step(path: GenderPath, index: int) -> Step | None:
    steps = steps_for(path)
    if 0 <= index < len(steps):
        return steps[index]
    return None


def all_questions(path: GenderPath) -> dict[str, Question]:
    return {q.key: q for step in steps_for(path) for q in step.questions}


# --------------------------------------------------------------- validation --

_LIST_FIELDS = {"equipment", "goals", "dietary_tags", "allergies", "disliked_foods", "preferred_days"}
_INT_FIELDS = {"birth_year", "height_cm", "weekly_frequency", "session_minutes", "meals_per_day"}
_FLOAT_FIELDS = {"weight_kg"}


def validate_step(step: Step, raw: dict[str, list[str]]) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate one submitted step.

    Returns ``(cleaned_answers, errors)``. Cleaned answers are JSON-friendly and
    keyed by question key; errors are keyed the same way for inline display.
    """
    cleaned: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for question in step.questions:
        values = [value.strip() for value in raw.get(question.key, []) if value.strip()]

        if question.type == "multi":
            allowed = question.option_values()
            chosen = [value for value in values if value in allowed]
            if question.required and not chosen:
                errors[question.key] = "צריך לבחור לפחות אפשרות אחת"
                continue
            if question.max_choices and len(chosen) > question.max_choices:
                errors[question.key] = f"אפשר לבחור עד {question.max_choices}"
                continue
            cleaned[question.key] = chosen
            continue

        value = values[0] if values else ""

        if not value:
            if question.required:
                errors[question.key] = "שדה חובה"
            else:
                cleaned[question.key] = [] if question.key in _LIST_FIELDS else ""
            continue

        if question.type == "single":
            if value not in question.option_values():
                errors[question.key] = "בחירה לא תקינה"
                continue
            cleaned[question.key] = value
            continue

        if question.type == "number":
            try:
                number: float | int = float(value.replace(",", "."))
            except ValueError:
                errors[question.key] = "צריך להזין מספר"
                continue
            if question.min_value is not None and number < question.min_value:
                errors[question.key] = f"המספר צריך להיות לפחות {question.min_value}"
                continue
            if question.max_value is not None and number > question.max_value:
                errors[question.key] = f"המספר צריך להיות עד {question.max_value}"
                continue
            cleaned[question.key] = number
            continue

        # free text
        if len(value) > 400:
            errors[question.key] = "הטקסט ארוך מדי"
            continue
        if question.key in _LIST_FIELDS:
            cleaned[question.key] = [part.strip() for part in value.split(",") if part.strip()]
        else:
            cleaned[question.key] = value

    return cleaned, errors


def profile_updates(path: GenderPath, answers: dict[str, Any]) -> dict[str, Any]:
    """Project questionnaire answers onto profile columns."""
    questions = all_questions(path)
    updates: dict[str, Any] = {}
    for key, value in answers.items():
        question = questions.get(key)
        if not question or not question.profile_field:
            continue
        field_name = question.profile_field
        if field_name in _INT_FIELDS:
            try:
                updates[field_name] = int(float(value))
            except (TypeError, ValueError):
                continue
        elif field_name in _FLOAT_FIELDS:
            try:
                updates[field_name] = float(value)
            except (TypeError, ValueError):
                continue
        elif field_name in _LIST_FIELDS:
            updates[field_name] = value if isinstance(value, list) else [value]
        else:
            updates[field_name] = value
    return updates
