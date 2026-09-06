"""Admin console access, CRUD and the audit trail (22-28, 46)."""

from __future__ import annotations

from .helpers import AppTestCase

from fitness_platform.db.repositories import content as content_repo, food as food_repo, insights, users as users_repo
from fitness_platform.db.seed import seed
from fitness_platform.domain.gender import GenderPath

ADMIN_PAGES = (
    "/admin",
    "/admin/users",
    "/admin/billing",
    "/admin/videos",
    "/admin/programs",
    "/admin/programs?tab=recipes",
    "/admin/ai",
    "/admin/analytics",
    "/admin/settings",
)


class AdminAccessTest(AppTestCase):
    def setUp(self):
        super().setUp()
        seed()

    def test_admin_reaches_every_console_page(self):
        client = self.new_client()
        client.login("admin@example.com", "Aa123456")
        for page in ADMIN_PAGES:
            self.assertEqual(client.get(page).status, 200, page)

    def test_member_is_forbidden_everywhere_in_the_console(self):
        client = self.new_client()
        client.login("noa@example.com", "Aa123456")
        for page in ADMIN_PAGES:
            self.assertEqual(client.get(page).status, 403, page)

    def test_anonymous_visitor_is_unauthorised(self):
        client = self.new_client()
        for page in ADMIN_PAGES:
            self.assertEqual(client.get(page).status, 401, page)

    def test_member_cannot_use_admin_write_endpoints(self):
        client = self.new_client()
        client.login("daniel@example.com", "Aa123456")
        self.assertEqual(client.post("/admin/videos", {"title": "פריצה"}).status, 403)
        self.assertEqual(client.post_json("/api/admin/videos/1/publish").status, 403)
        self.assertEqual(client.post("/admin/users/2/status", {"status": "suspended"}).status, 403)

    def test_denied_access_is_audited(self):
        client = self.new_client()
        client.login("noa@example.com", "Aa123456")
        client.get("/admin")
        actions = [row["action"] for row in insights.list_audit(5)]
        self.assertIn("access_denied", actions)


class AdminContentTest(AppTestCase):
    def setUp(self):
        super().setUp()
        seed()
        self.client.login("admin@example.com", "Aa123456")

    def test_create_video_requires_a_scope_and_is_audited(self):
        self.client.post(
            "/admin/videos",
            {"title": "אימון חדש", "duration": "25", "difficulty": "beginner",
             "category": "core", "gender_path": "male", "published": "1"},
        )
        created = content_repo.admin_list_videos(search="אימון חדש")
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].gender_path.value, "male")
        self.assertTrue(created[0].published)
        self.assertIn("video_created", [row["action"] for row in insights.list_audit(5)])

    def test_created_video_appears_only_on_its_path(self):
        self.client.post(
            "/admin/videos",
            {"title": "בלעדי לגברים", "duration": "25", "difficulty": "beginner",
             "category": "core", "gender_path": "male", "published": "1"},
        )
        female_titles = {video.title for video in content_repo.list_videos(GenderPath.FEMALE, limit=100)}
        male_titles = {video.title for video in content_repo.list_videos(GenderPath.MALE, limit=100)}
        self.assertNotIn("בלעדי לגברים", female_titles)
        self.assertIn("בלעדי לגברים", male_titles)

    def test_unpublished_video_is_invisible_to_members(self):
        self.client.post(
            "/admin/videos",
            {"title": "טיוטה", "duration": "25", "difficulty": "beginner",
             "category": "core", "gender_path": "female"},
        )
        titles = {video.title for video in content_repo.list_videos(GenderPath.FEMALE, limit=100)}
        self.assertNotIn("טיוטה", titles)

    def test_invalid_duration_does_not_break_the_form(self):
        response = self.client.post(
            "/admin/videos",
            {"title": "משך לא תקין", "duration": "abc", "gender_path": "female", "published": "1"},
        )
        self.assertEqual(response.status, 303)
        self.assertEqual(content_repo.admin_list_videos(search="משך לא תקין")[0].duration, 0)

    def test_video_update_and_delete(self):
        video = content_repo.admin_list_videos(limit=1)[0]
        self.client.post(
            f"/admin/videos/{video.id}",
            {"title": "כותרת מעודכנת", "duration": "31", "difficulty": "beginner",
             "category": "core", "gender_path": video.gender_path.value, "published": "1"},
        )
        self.assertEqual(content_repo.get_video(video.id).title, "כותרת מעודכנת")
        self.client.post(f"/admin/videos/{video.id}/delete")
        self.assertIsNone(content_repo.get_video(video.id))

    def test_recipe_approval_gates_the_meal_engine(self):
        self.client.post(
            "/admin/recipes",
            {"name": "מתכון ממתין", "meal_type": "lunch", "gender_path": "all",
             "ingredients": "עגבנייה | 2 | יחידות", "instructions": "לחתוך", "prep_minutes": "10"},
        )
        pending = food_repo.admin_list_recipes(search="מתכון ממתין")[0]
        self.assertFalse(pending.approved)
        self.assertNotIn(pending.id, [r.id for r in food_repo.list_recipes(GenderPath.FEMALE, limit=100)])

        self.client.post(f"/admin/recipes/{pending.id}/approve", {"approved": "1"})
        self.assertIn(pending.id, [r.id for r in food_repo.list_recipes(GenderPath.FEMALE, limit=100)])

    def test_recipe_ingredients_are_parsed_from_the_form(self):
        self.client.post(
            "/admin/recipes",
            {"name": "מתכון מפורק", "meal_type": "dinner", "gender_path": "all",
             "ingredients": "עוף | 300 | גרם\nאורז | 100 | גרם", "instructions": "לבשל\nלהגיש",
             "prep_minutes": "20", "approved": "1"},
        )
        recipe = food_repo.admin_list_recipes(search="מתכון מפורק")[0]
        self.assertEqual(len(recipe.ingredients), 2)
        self.assertEqual(recipe.ingredients[0]["name"], "עוף")
        self.assertEqual(recipe.instructions, ["לבשל", "להגיש"])

    def test_program_creation(self):
        self.client.post(
            "/admin/programs",
            {"name": "תוכנית חדשה", "duration_weeks": "6", "difficulty": "intermediate",
             "gender_path": "female", "goal_tags": "tone, strength", "published": "1"},
        )
        program = [p for p in content_repo.admin_list_programs() if p.name == "תוכנית חדשה"][0]
        self.assertEqual(program.duration_weeks, 6)
        self.assertEqual(program.goal_tags, ["tone", "strength"])

    def test_user_suspension_ends_the_session(self):
        member = self.new_client()
        member.login("noa@example.com", "Aa123456")
        self.assertEqual(member.get("/women/dashboard").status, 200)

        user = users_repo.get_user_by_email("noa@example.com")
        self.client.post(f"/admin/users/{user.id}/status", {"status": "suspended"})
        self.assertEqual(member.get("/women/dashboard").status, 401)

    def test_coach_details_are_editable(self):
        coach = content_repo.list_coaches()[0]
        self.client.post(f"/admin/coaches/{coach.id}", {"name": "שם חדש", "bio": "ביו", "photo_url": ""})
        self.assertEqual(content_repo.get_coach(coach.id).name, "שם חדש")


class AdminApiTest(AppTestCase):
    def setUp(self):
        super().setUp()
        seed()
        self.client.login("admin@example.com", "Aa123456")

    def test_stats_endpoint(self):
        payload = self.client.get("/api/admin/stats").json()
        self.assertEqual(payload["users"]["female"], 1)
        self.assertEqual(payload["users"]["male"], 1)

    def test_health_reports_mock_providers(self):
        payload = self.client.get("/api/admin/health").json()
        self.assertTrue(payload["ai"]["mock"])
        self.assertTrue(payload["payments"]["mock"])

    def test_publish_toggle_is_audited(self):
        video = content_repo.admin_list_videos(limit=1)[0]
        before = video.published
        payload = self.client.post_json(f"/api/admin/videos/{video.id}/publish").json()
        self.assertNotEqual(payload["published"], before)
        self.assertIn("video_publish_toggled", [row["action"] for row in insights.list_audit(3)])
