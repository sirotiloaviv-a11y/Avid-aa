"""Member screens, ownership checks and the public site (11, 12, 13, 37, 47)."""

from __future__ import annotations

from .helpers import AppTestCase

from fitness_platform.db.repositories import content as content_repo, food as food_repo, users as users_repo
from fitness_platform.db.seed import seed
from fitness_platform.domain.gender import GenderPath
from fitness_platform.services import meal_service


class PublicSiteTest(AppTestCase):
    def test_landing_offers_both_paths(self):
        page = self.client.get("/")
        self.assertEqual(page.status, 200)
        self.assertIn("מי מתאמן איתנו?", page.text)
        self.assertIn("/start/women", page.text)
        self.assertIn("/start/men", page.text)

    def test_pages_are_rtl_and_hebrew(self):
        for path in ("/", "/pricing", "/start", "/login", "/legal/privacy", "/legal/terms"):
            page = self.client.get(path)
            self.assertEqual(page.status, 200, path)
            self.assertIn('dir="rtl"', page.text, path)
            self.assertIn('lang="he"', page.text, path)

    def test_signup_page_is_themed_per_path(self):
        self.assertIn("theme-women", self.client.get("/start/women").text)
        self.assertIn("theme-men", self.client.get("/start/men").text)

    def test_unknown_path_segment_redirects(self):
        self.assertEqual(self.client.get("/start/other").location, "/start")

    def test_pricing_lists_both_plans(self):
        page = self.client.get("/pricing")
        self.assertIn("מנוי חודשי", page.text)
        self.assertIn("מנוי שנתי", page.text)

    def test_missing_page_renders_a_friendly_404(self):
        page = self.client.get("/no-such-page")
        self.assertEqual(page.status, 404)
        self.assertIn("לא מצאנו", page.text)
        self.assertNotIn("Traceback", page.text)


class MemberScreenTest(AppTestCase):
    def setUp(self):
        super().setUp()
        seed()
        self.client.login("noa@example.com", "Aa123456")

    def test_dashboard_shows_the_key_cards(self):
        page = self.client.get("/women/dashboard")
        for text in ("האימון שלך היום", "תפריט היום", "רשימת קניות", "ההתקדמות שלך", "יעדים שבועיים", "AI Coach"):
            self.assertIn(text, page.text, text)

    def test_dashboard_uses_the_womens_theme_and_wording(self):
        page = self.client.get("/women/dashboard")
        self.assertIn("theme-women", page.text)
        self.assertIn("התחילי אימון", page.text)

    def test_mens_dashboard_uses_the_mens_theme_and_wording(self):
        client = self.new_client()
        client.login("daniel@example.com", "Aa123456")
        page = client.get("/men/dashboard")
        self.assertIn("theme-men", page.text)
        self.assertIn("התחל אימון", page.text)

    def test_workout_filters(self):
        filtered = self.client.get("/women/workouts", query={"category": "core"})
        self.assertEqual(filtered.status, 200)
        empty = self.client.get("/women/workouts", query={"q": "לא-קיים-בכלל"})
        self.assertIn("לא מצאנו אימונים מתאימים", empty.text)

    def test_completing_a_workout_records_progress(self):
        video = content_repo.list_videos(GenderPath.FEMALE, limit=1)[0]
        user = users_repo.get_user_by_email("noa@example.com")
        self.client.post(f"/women/workouts/{video.id}/complete")
        self.assertIn(video.id, content_repo.completed_video_ids(user.id))
        self.assertEqual(content_repo.completed_count(user.id), 1)

    def test_starting_a_program_assigns_it(self):
        program = content_repo.list_programs(GenderPath.FEMALE)[0]
        user = users_repo.get_user_by_email("noa@example.com")
        self.client.post(f"/women/programs/{program.id}/start")
        self.assertEqual(content_repo.active_program_id(user.id), program.id)

    def test_meal_plan_is_created_on_first_visit(self):
        user = users_repo.get_user_by_email("noa@example.com")
        self.assertIsNone(food_repo.latest_meal_plan(user.id))
        self.client.get("/women/meals")
        self.assertIsNotNone(food_repo.latest_meal_plan(user.id))

    def test_shopping_list_is_derived_from_the_plan(self):
        self.client.get("/women/meals")
        self.client.post("/women/shopping/build")
        page = self.client.get("/women/shopping")
        self.assertIn("list-row", page.text)

    def test_progress_entry_is_validated(self):
        bad = self.client.post("/women/progress", {"weight_kg": "לא מספר"})
        self.assertIn("tone=error", bad.location)
        good = self.client.post("/women/progress", {"weight_kg": "61.5", "note": "מרגישה טוב"})
        self.assertNotIn("tone=error", good.location)

    def test_settings_updates_the_profile(self):
        user = users_repo.get_user_by_email("noa@example.com")
        self.client.post(
            "/women/settings",
            {"name": "נועה כהן לוי", "weekly_frequency": "5", "session_minutes": "45", "equipment": ["mat", "gym"]},
        )
        profile = users_repo.get_profile(user.id)
        self.assertEqual(profile.weekly_frequency, 5)
        self.assertEqual(sorted(profile.equipment), ["gym", "mat"])
        self.assertEqual(users_repo.get_user(user.id).name, "נועה כהן לוי")

    def test_settings_clamps_out_of_range_values(self):
        user = users_repo.get_user_by_email("noa@example.com")
        self.client.post("/women/settings", {"name": "נועה", "weekly_frequency": "99", "session_minutes": "1"})
        profile = users_repo.get_profile(user.id)
        self.assertEqual(profile.weekly_frequency, 7)
        self.assertEqual(profile.session_minutes, 10)

    def test_community_shows_an_honest_empty_state(self):
        page = self.client.get("/women/community")
        self.assertIn("הקהילה נפתחת בקרוב", page.text)


class OwnershipTest(AppTestCase):
    def setUp(self):
        super().setUp()
        seed()
        self.owner = self.new_client()
        self.owner.login("noa@example.com", "Aa123456")
        self.other = self.new_client()
        self.other.login("daniel@example.com", "Aa123456")

    def test_one_member_cannot_toggle_another_members_list(self):
        payload = self.owner.post_json("/api/shopping-lists/build").json()
        item_id = payload["items"][0]["id"]
        self.assertEqual(self.other.post_json(f"/api/shopping/items/{item_id}/toggle", {"checked": True}).status, 403)
        self.assertEqual(self.other.post_json(f"/api/shopping/items/{item_id}/delete").status, 403)

    def test_meal_plans_are_per_member(self):
        first = self.owner.get("/api/meal-plans/current").json()["plan_id"]
        second = self.other.get("/api/meal-plans/current").json()["plan_id"]
        self.assertNotEqual(first, second)

    def test_deleted_account_loses_access_and_personal_rows(self):
        user = users_repo.get_user_by_email("noa@example.com")
        self.owner.post("/women/settings/delete")
        self.assertEqual(self.owner.get("/women/dashboard").status, 401)
        self.assertIsNone(users_repo.get_user(user.id))
        self.assertIsNone(users_repo.get_user_by_email("noa@example.com"))


class EmptyStateTest(AppTestCase):
    """A member on a path with no content still gets a finished screen (37)."""

    def setUp(self):
        super().setUp()
        seed(with_demo_users=False)
        from fitness_platform.db.connection import execute

        execute("DELETE FROM videos WHERE gender_path = 'female'")
        execute("DELETE FROM recipes WHERE gender_path IN ('female', 'all')")
        execute("DELETE FROM workout_programs WHERE gender_path = 'female'")

        self.client.signup("women", "empty@example.com")
        from .test_onboarding import complete_questionnaire

        complete_questionnaire(self.client)
        user = users_repo.get_user_by_email("empty@example.com")
        from fitness_platform.db.repositories import billing as billing_repo
        from fitness_platform.domain.subscription import SubscriptionStatus

        subscription_id = billing_repo.create_subscription(user.id, "monthly", 14900)
        billing_repo.set_status(subscription_id, SubscriptionStatus.ACTIVE, period_days=30)

    def test_dashboard_renders_without_content(self):
        page = self.client.get("/women/dashboard")
        self.assertEqual(page.status, 200)
        self.assertIn("empty-state", page.text)
        self.assertNotIn("Traceback", page.text)

    def test_every_member_screen_renders_without_content(self):
        for route in ("/women/workouts", "/women/programs", "/women/meals", "/women/shopping", "/women/progress"):
            self.assertEqual(self.client.get(route).status, 200, route)

    def test_plan_preview_explains_that_content_is_coming(self):
        page = self.client.get("/onboarding/ready")
        self.assertIn("מכינים עבורך את התוכנית", page.text)
