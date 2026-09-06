"""Seed content for development and demos (40).

Two coaches, a library of workouts and recipes per path, and four programs.
Everything here is tagged with a ``gender_path``, so the seeded database
exercises the isolation rule rather than papering over it. The function is
idempotent: running it twice does not duplicate rows.
"""

from __future__ import annotations

from ..domain.gender import ContentScope, GenderPath
from ..domain.roles import Role
from ..services.security import hash_password
from .connection import scalar
from .repositories import content as content_repo, food as food_repo, users as users_repo

FEMALE_COACH = ("מאיה לוי", "מאמנת כושר ופילאטיס, מתמחה באימוני חיזוק וחיטוב לנשים בכל הרמות.")
MALE_COACH = ("איתי ברק", "מאמן כוח וכושר תפקודי, מתמחה בבניית מסה, כוח וסיבולת.")

_FEMALE_VIDEOS = [
    ("גוף מלא — 30 דקות", "אימון גוף מלא מאוזן עם דגש על חיזוק וייצוב.", 30, "beginner", "full_body", ["mat"], ["חיזוק", "גוף מלא"]),
    ("פלג גוף תחתון וישבן", "עבודה ממוקדת על רגליים וישבן עם משקל גוף וגומייה.", 35, "intermediate", "lower_body", ["mat", "bands"], ["ישבן", "רגליים"]),
    ("בטן וליבה — 15 דקות", "סדרת תרגילי ליבה קצרה ויעילה לסיום היום.", 15, "beginner", "core", ["mat"], ["ליבה", "קצר"]),
    ("פילאטיס בוקר", "רצף פילאטיס עדין שפותח את הגוף ומייצב את הגב.", 25, "beginner", "stretch", ["mat"], ["פילאטיס", "גמישות"]),
    ("אימון כוח עם משקולות", "בניית כוח עם משקולות יד — פלג גוף עליון ותחתון.", 40, "intermediate", "full_body", ["dumbbells"], ["כוח"]),
    ("HIIT קצר לשריפה", "אינטרוולים מהירים לשיפור כושר לב־ריאה.", 20, "intermediate", "short_workout", [], ["hiit", "קרדיו"]),
    ("חימום לפני אימון", "חמש דקות חימום שמכינות את הגוף ומפחיתות סיכון לפציעה.", 5, "beginner", "warmup", [], ["חימום"]),
    ("מתיחות ערב", "מתיחות רגועות לשחרור מתח בסוף היום.", 12, "beginner", "stretch", ["mat"], ["מתיחות"]),
    ("זרועות וכתפיים", "חיטוב פלג גוף עליון עם התנגדות קלה.", 25, "intermediate", "upper_body", ["dumbbells", "bands"], ["זרועות"]),
    ("טכניקה: סקוואט נכון", "פירוק תנועת הסקוואט צעד אחר צעד.", 8, "beginner", "technique", [], ["טכניקה"]),
    ("אימון מתקדם — כוח וסיבולת", "אתגר לרמות מתקדמות, שילוב כוח וסיבולת.", 45, "advanced", "full_body", ["dumbbells", "kettlebell"], ["מתקדם"]),
    ("איך בונים שגרת אימונים", "הסבר קצר על תכנון שבוע אימונים שמחזיק לאורך זמן.", 10, "beginner", "education", [], ["הסבר"]),
]

_MALE_VIDEOS = [
    ("גוף מלא — 45 דקות", "אימון גוף מלא לבניית כוח ומסה.", 45, "intermediate", "full_body", ["dumbbells"], ["כוח", "מסה"]),
    ("חזה וטרייספס", "אימון דחיפה קלאסי עם התקדמות מבוקרת.", 40, "intermediate", "upper_body", ["dumbbells"], ["חזה"]),
    ("גב ובייספס", "אימון משיכה לחיזוק הגב ושיפור היציבה.", 40, "intermediate", "upper_body", ["dumbbells", "pullup_bar"], ["גב"]),
    ("רגליים — יום כוח", "סקוואט, לאנג׳ ותרגילי ייצוב לרגליים חזקות.", 45, "advanced", "lower_body", ["barbell"], ["רגליים"]),
    ("ליבה וייצוב", "חיזוק הליבה כבסיס לכל תרגיל כוח.", 20, "beginner", "core", ["mat"], ["ליבה"]),
    ("אימון קצר במשקל גוף", "עשרים דקות בלי ציוד, בכל מקום.", 20, "beginner", "short_workout", [], ["משקל גוף"]),
    ("חימום דינמי", "חימום מפרקים ושרירים לפני אימון כוח.", 6, "beginner", "warmup", [], ["חימום"]),
    ("שחרור ומתיחות", "מתיחות אחרי אימון לשיפור ההתאוששות.", 12, "beginner", "stretch", ["mat"], ["מתיחות"]),
    ("HIIT לשריפת שומן", "אינטרוולים בעצימות גבוהה לחיטוב.", 25, "advanced", "short_workout", [], ["hiit"]),
    ("טכניקה: דדליפט", "מבנה התנועה, טעויות נפוצות ותיקונים.", 9, "intermediate", "technique", ["barbell"], ["טכניקה"]),
    ("אימון מתחילים — שבוע ראשון", "כניסה רכה לאימון כוח עבור מתחילים.", 30, "beginner", "full_body", ["mat"], ["מתחילים"]),
    ("תזונה סביב אימון", "מה כדאי לאכול לפני ואחרי אימון — הסבר קצר.", 11, "beginner", "education", [], ["תזונה"]),
]

_SHARED_RECIPES = [
    ("שיבולת שועל עם פירות", "breakfast", 10, ["vegetarian", "high_protein"], [], ["dairy"],
     [("שיבולת שועל", "60", "גרם"), ("חלב", "200", 'מ"ל'), ("בננה", "1", "יחידה"), ("דבש", "1", "כפית")],
     ["מחממים את החלב עם השיבולת על אש נמוכה.", "מבשלים 5 דקות עד להסמכה.", "מוסיפים בננה פרוסה ודבש."]),
    ("חביתת ירק וגבינה", "breakfast", 12, ["vegetarian", "gluten_free", "high_protein"], [], ["eggs", "dairy"],
     [("ביצים", "3", "יחידות"), ("תרד", "חופן", ""), ("גבינה בולגרית", "40", "גרם"), ("שמן זית", "1", "כפית")],
     ["מטגנים את התרד קלות בשמן זית.", "טורפים את הביצים ויוצקים למחבת.", "מפוררים גבינה ומקפלים."]),
    ("סלט קינואה וחומוס", "lunch", 20, ["vegetarian", "vegan", "gluten_free"], [], [],
     [("קינואה", "100", "גרם"), ("חומוס מבושל", "150", "גרם"), ("עגבניות שרי", "8", "יחידות"),
      ("מלפפון", "1", "יחידה"), ("לימון", "חצי", ""), ("שמן זית", "1", "כף")],
     ["מבשלים קינואה לפי ההוראות ומצננים.", "חותכים ירקות לקוביות.", "מערבבים הכול עם לימון ושמן זית."]),
    ("חזה עוף בתנור עם בטטה", "dinner", 35, ["gluten_free", "high_protein", "kosher"], [], [],
     [("חזה עוף", "300", "גרם"), ("בטטה", "2", "יחידות"), ("שמן זית", "1", "כף"), ("פפריקה", "1", "כפית")],
     ["מחממים תנור ל‑200 מעלות.", "חותכים בטטה לקוביות ומתבלים.", "אופים 25 דקות יחד עם העוף."]),
    ("סלמון עם ירקות מוקפצים", "dinner", 25, ["gluten_free", "high_protein"], [], ["fish"],
     [("פילה סלמון", "200", "גרם"), ("ברוקולי", "200", "גרם"), ("גזר", "1", "יחידה"), ("שמן זית", "1", "כף")],
     ["צורבים את הסלמון 4 דקות מכל צד.", "מוקפצים את הירקות במחבת נפרדת.", "מגישים יחד."]),
    ("יוגורט עם אגוזים ופירות", "snack", 5, ["vegetarian", "gluten_free", "high_protein"], [], ["dairy", "nuts"],
     [("יוגורט יווני", "200", "גרם"), ("אגוזי מלך", "20", "גרם"), ("תות", "5", "יחידות")],
     ["מערבבים את הכול בקערה."]),
    ("טוסט אבוקדו וביצה", "breakfast", 10, ["vegetarian", "high_protein"], [], ["eggs", "gluten"],
     [("לחם מלא", "2", "פרוסות"), ("אבוקדו", "1", "יחידה"), ("ביצה", "1", "יחידה")],
     ["קולים את הלחם.", "מועכים אבוקדו ומורחים.", "מוסיפים ביצה עלומה."]),
    ("מרק עדשים", "lunch", 40, ["vegetarian", "vegan", "gluten_free", "kosher"], [], [],
     [("עדשים כתומות", "200", "גרם"), ("גזר", "2", "יחידות"), ("בצל", "1", "יחידה"), ("שמן זית", "1", "כף")],
     ["מטגנים בצל וגזר.", "מוסיפים עדשים ומים ומבשלים 30 דקות.", "מתבלים ומגישים."]),
    ("קערת טופו וירקות", "dinner", 25, ["vegetarian", "vegan"], [], ["soy"],
     [("טופו", "200", "גרם"), ("אורז מלא", "100", "גרם"), ("קישוא", "1", "יחידה"), ("רוטב סויה", "1", "כף")],
     ["מטגנים טופו עד הזהבה.", "מבשלים אורז.", "מוקפצים ירקות ומחברים הכול."]),
    ("שייק חלבון וקקאו", "snack", 5, ["vegetarian", "high_protein", "gluten_free"], [], ["dairy"],
     [("חלב", "250", 'מ"ל'), ("אבקת חלבון", "30", "גרם"), ("בננה", "1", "יחידה"), ("קקאו", "1", "כפית")],
     ["מכניסים הכול לבלנדר ומערבבים דקה."]),
    ("פסטה מלאה ברוטב עגבניות", "lunch", 25, ["vegetarian", "kosher"], [], ["gluten"],
     [("פסטה מלאה", "150", "גרם"), ("עגבניות מרוסקות", "400", "גרם"), ("בצל", "1", "יחידה"), ("שמן זית", "1", "כף")],
     ["מבשלים פסטה.", "מכינים רוטב עם בצל ועגבניות.", "מערבבים ומגישים."]),
    ("סלט טונה וירקות", "lunch", 12, ["gluten_free", "high_protein"], [], ["fish"],
     [("טונה במים", "1", "קופסה"), ("חסה", "חופן", ""), ("עגבנייה", "1", "יחידה"), ("שמן זית", "1", "כפית")],
     ["חותכים ירקות.", "מוסיפים טונה מסוננת.", "מתבלים בשמן זית ולימון."]),
]

_FEMALE_ONLY_RECIPES = [
    ("קערת בוקר עם תותים", "breakfast", 8, ["vegetarian", "gluten_free"], [], ["dairy"],
     [("יוגורט", "200", "גרם"), ("תות", "8", "יחידות"), ("שקדים", "15", "גרם")],
     ["מסדרים בקערה ומגישים."]),
    ("סלט ירוק עם גבינת עיזים", "dinner", 15, ["vegetarian", "gluten_free"], [], ["dairy"],
     [("חסה", "חופן", ""), ("גבינת עיזים", "50", "גרם"), ("אגוזי מלך", "20", "גרם"), ("שמן זית", "1", "כף")],
     ["מערבבים את כל המרכיבים."]),
]

_MALE_ONLY_RECIPES = [
    ("סטייק בקר עם אורז", "dinner", 30, ["gluten_free", "high_protein", "kosher"], [], [],
     [("סטייק בקר", "250", "גרם"), ("אורז", "120", "גרם"), ("שמן זית", "1", "כף")],
     ["צורבים את הסטייק לפי דרגת העשייה.", "מבשלים אורז ומגישים."]),
    ("אומלט חלבון גדול", "breakfast", 12, ["gluten_free", "high_protein"], [], ["eggs"],
     [("חלבון ביצה", "5", "יחידות"), ("ביצה שלמה", "1", "יחידה"), ("פטריות", "100", "גרם")],
     ["מטגנים פטריות.", "יוצקים את הביצים ומבשלים."]),
]


def _has_content() -> bool:
    return bool(scalar("SELECT COUNT(*) FROM videos"))


def seed(*, with_demo_users: bool = True, verbose: bool = False) -> dict[str, int]:
    """Populate the database. Safe to run repeatedly."""
    counts = {"coaches": 0, "videos": 0, "recipes": 0, "programs": 0, "users": 0}

    if _has_content():
        if verbose:
            print("content already seeded — skipping")
    else:
        female_coach = content_repo.create_coach(FEMALE_COACH[0], ContentScope.FEMALE, bio=FEMALE_COACH[1])
        male_coach = content_repo.create_coach(MALE_COACH[0], ContentScope.MALE, bio=MALE_COACH[1])
        counts["coaches"] = 2

        video_ids: dict[str, list[int]] = {"female": [], "male": []}
        for scope, coach_id, rows in (
            ("female", female_coach, _FEMALE_VIDEOS),
            ("male", male_coach, _MALE_VIDEOS),
        ):
            for title, description, duration, difficulty, category, equipment, tags in rows:
                video_ids[scope].append(
                    content_repo.create_video(
                        title=title,
                        description=description,
                        duration=duration,
                        difficulty=difficulty,
                        category=category,
                        gender_path=scope,
                        coach_id=coach_id,
                        equipment=equipment,
                        tags=tags,
                        published=1,
                    )
                )
                counts["videos"] += 1

        for scope, rows in (
            ("all", _SHARED_RECIPES),
            ("female", _FEMALE_ONLY_RECIPES),
            ("male", _MALE_ONLY_RECIPES),
        ):
            for name, meal_type, prep, dietary, tags, allergens, ingredients, instructions in rows:
                food_repo.create_recipe(
                    name=name,
                    description=f"{name} — מתכון מאושר על ידי צוות התוכן.",
                    ingredients=[{"name": item, "amount": amount, "unit": unit} for item, amount, unit in ingredients],
                    instructions=instructions,
                    meal_type=meal_type,
                    dietary_tags=dietary,
                    tags=tags or dietary,
                    allergens=allergens,
                    gender_path=scope,
                    prep_minutes=prep,
                    approved=1,
                )
                counts["recipes"] += 1

        counts["programs"] = _seed_programs(video_ids)

    if with_demo_users:
        counts["users"] = _seed_users()

    return counts


def _seed_programs(video_ids: dict[str, list[int]]) -> int:
    plans = (
        ("female", "מסלול התחלה לנשים", "ארבעה שבועות של בנייה הדרגתית — חיזוק, ליבה וגמישות.", 4, "beginner", ["tone", "routine", "energy"], ["mat"]),
        ("female", "חיטוב וכוח — מתקדמות", "שישה שבועות עם דגש על כוח, ישבן וליבה.", 6, "intermediate", ["tone", "strength"], ["dumbbells", "bands"]),
        ("male", "בסיס כוח לגברים", "ארבעה שבועות לבניית בסיס כוח ותנועה נכונה.", 4, "beginner", ["strength", "routine"], ["mat"]),
        ("male", "מסה וכוח — מתקדם", "שישה שבועות של אימוני דחיפה, משיכה ורגליים.", 6, "intermediate", ["muscle", "strength"], ["dumbbells"]),
    )
    day_titles = (
        ("גוף מלא", "חיזוק כללי", False),
        ("מנוחה פעילה", "הליכה או מתיחות", True),
        ("פלג גוף עליון", "דחיפה ומשיכה", False),
        ("ליבה", "ייצוב מרכז הגוף", False),
        ("פלג גוף תחתון", "רגליים וישבן", False),
        ("מנוחה", "התאוששות", True),
        ("אימון בחירה", "מה שמתאים לך היום", False),
    )
    created = 0
    for scope, name, description, weeks, difficulty, goals, equipment in plans:
        program_id = content_repo.create_program(
            name=name,
            description=description,
            gender_path=scope,
            duration_weeks=weeks,
            difficulty=difficulty,
            goal_tags=goals,
            equipment=equipment,
            published=1,
        )
        pool = video_ids[scope]
        for index, (title, focus, is_rest) in enumerate(day_titles, start=1):
            day_id = content_repo.add_program_day(program_id, index, title, focus, is_rest)
            if not is_rest and pool:
                picks = [pool[(index + offset) % len(pool)] for offset in range(2)]
                content_repo.set_day_videos(day_id, picks)
        created += 1
    return created


def _seed_users() -> int:
    created = 0
    demo = (
        ("admin@example.com", "מנהל המערכת", Role.ADMIN, None),
        ("noa@example.com", "נועה כהן", Role.USER, GenderPath.FEMALE),
        ("daniel@example.com", "דניאל לוי", Role.USER, GenderPath.MALE),
    )
    for email, name, role, path in demo:
        if users_repo.email_exists(email):
            continue
        user_id = users_repo.create_user(
            email, hash_password("Aa123456"), name=name, gender_path=path, role=role
        )
        created += 1
        if path is None:
            continue
        users_repo.update_profile(
            user_id,
            {
                "display_name": name.split(" ")[0],
                "experience_level": "beginner" if path is GenderPath.FEMALE else "intermediate",
                "weekly_frequency": 4,
                "session_minutes": 30 if path is GenderPath.FEMALE else 45,
                "equipment": ["mat", "bands"] if path is GenderPath.FEMALE else ["dumbbells", "mat"],
                "goals": ["tone", "energy"] if path is GenderPath.FEMALE else ["muscle", "strength"],
                "dietary_tags": ["vegetarian"] if path is GenderPath.FEMALE else ["high_protein"],
                "allergies": [],
                "preferred_days": ["sun", "tue", "thu", "sat"],
                "meals_per_day": 3,
            },
        )
        users_repo.mark_onboarding_complete(user_id)
        _activate_demo_subscription(user_id)
    return created


def _activate_demo_subscription(user_id: int) -> None:
    from ..domain.subscription import SubscriptionStatus
    from .repositories import billing as billing_repo

    subscription_id = billing_repo.create_subscription(user_id, "monthly", 14900, provider="mock", provider_ref=f"seed_{user_id}")
    billing_repo.set_status(subscription_id, SubscriptionStatus.ACTIVE, period_days=30)
    billing_repo.record_payment(user_id, subscription_id, 14900, "succeeded", provider="mock", provider_ref=f"seed_{user_id}")
