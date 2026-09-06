"""The rule the product cannot ship without (2, 14, 53).

If any test in this file fails, a member can reach the other path's product
area or content. Everything else in the suite is quality; this file is the
contract.
"""

from __future__ import annotations

from .helpers import AppTestCase

from fitness_platform.db.repositories import content as content_repo, food as food_repo
from fitness_platform.db.seed import seed
from fitness_platform.domain.gender import ContentScope, GenderPath, can_view, filter_visible, scope_sql
from fitness_platform.domain.models import Profile
from fitness_platform.domain.rules_engine import assert_scope

FEMALE_ROUTES = (
    "/women/dashboard",
    "/women/workouts",
    "/women/programs",
    "/women/meals",
    "/women/shopping",
    "/women/progress",
    "/women/community",
    "/women/coach",
    "/women/settings",
)
MALE_ROUTES = tuple(route.replace("/women/", "/men/") for route in FEMALE_ROUTES)


class GenderRulesTest(AppTestCase):
    def test_can_view_matrix(self):
        female, male = GenderPath.FEMALE, GenderPath.MALE
        self.assertTrue(can_view(female, "female"))
        self.assertTrue(can_view(female, "all"))
        self.assertFalse(can_view(female, "male"))
        self.assertTrue(can_view(male, "male"))
        self.assertTrue(can_view(male, "all"))
        self.assertFalse(can_view(male, "female"))
        self.assertFalse(can_view(None, "all"))
        self.assertFalse(can_view(female, "everything"))
        self.assertFalse(can_view(female, None))

    def test_scope_sql_is_parameterised(self):
        clause, params = scope_sql(GenderPath.FEMALE)
        self.assertEqual(clause, "gender_path IN (?, ?)")
        self.assertEqual(params, ["female", "all"])

    def test_filter_visible_drops_foreign_rows(self):
        rows = [{"gender_path": "female"}, {"gender_path": "male"}, {"gender_path": "all"}]
        self.assertEqual(len(filter_visible(GenderPath.FEMALE, rows)), 2)

    def test_content_scope_parsing(self):
        self.assertIs(ContentScope.parse("ALL"), ContentScope.ALL)
        self.assertIs(ContentScope.parse(GenderPath.MALE), ContentScope.MALE)
        self.assertIsNone(ContentScope.parse("nonsense"))


class RepositoryIsolationTest(AppTestCase):
    def setUp(self):
        super().setUp()
        seed(with_demo_users=False)

    def test_video_lists_never_cross(self):
        for path in (GenderPath.FEMALE, GenderPath.MALE):
            other = "male" if path is GenderPath.FEMALE else "female"
            for video in content_repo.list_videos(path, limit=100):
                self.assertNotEqual(video.gender_path.value, other)

    def test_recipe_lists_never_cross(self):
        for path in (GenderPath.FEMALE, GenderPath.MALE):
            other = "male" if path is GenderPath.FEMALE else "female"
            for recipe in food_repo.list_recipes(path, limit=100):
                self.assertNotEqual(recipe.gender_path.value, other)

    def test_get_video_by_id_is_scoped(self):
        male_video = content_repo.list_videos(GenderPath.MALE, limit=1)[0]
        self.assertIsNone(content_repo.get_video(male_video.id, GenderPath.FEMALE))
        self.assertIsNotNone(content_repo.get_video(male_video.id, GenderPath.MALE))

    def test_get_recipe_by_id_is_scoped(self):
        male_recipes = [r for r in food_repo.admin_list_recipes(gender_path="male")]
        self.assertTrue(male_recipes)
        self.assertIsNone(food_repo.get_recipe(male_recipes[0].id, GenderPath.FEMALE))

    def test_get_program_by_id_is_scoped(self):
        male_program = content_repo.list_programs(GenderPath.MALE)[0]
        self.assertIsNone(content_repo.get_program(male_program.id, GenderPath.FEMALE))

    def test_rules_engine_scope_assertion(self):
        videos = content_repo.admin_list_videos(limit=100)
        kept = assert_scope(GenderPath.FEMALE, videos)
        self.assertTrue(kept)
        self.assertLess(len(kept), len(videos))
        self.assertTrue(all(video.gender_path.value != "male" for video in kept))


class RouteIsolationTest(AppTestCase):
    def setUp(self):
        super().setUp()
        seed()

    def _login(self, email):
        client = self.new_client()
        client.login(email, "Aa123456")
        return client

    def test_female_member_is_bounced_from_male_routes(self):
        client = self._login("noa@example.com")
        for route in MALE_ROUTES:
            response = client.get(route)
            self.assertEqual(response.status, 303, route)
            self.assertTrue(response.location.startswith("/women/"), f"{route} -> {response.location}")

    def test_male_member_is_bounced_from_female_routes(self):
        client = self._login("daniel@example.com")
        for route in FEMALE_ROUTES:
            response = client.get(route)
            self.assertEqual(response.status, 303, route)
            self.assertTrue(response.location.startswith("/men/"), f"{route} -> {response.location}")

    def test_own_routes_are_reachable(self):
        client = self._login("noa@example.com")
        for route in FEMALE_ROUTES:
            self.assertEqual(client.get(route).status, 200, route)

    def test_cross_path_video_page_is_not_found(self):
        client = self._login("noa@example.com")
        male_video = content_repo.list_videos(GenderPath.MALE, limit=1)[0]
        response = client.get(f"/women/workouts/{male_video.id}")
        self.assertEqual(response.status, 404)

    def test_cross_path_recipe_page_is_not_found(self):
        client = self._login("daniel@example.com")
        female_only = food_repo.admin_list_recipes(gender_path="female")[0]
        self.assertEqual(client.get(f"/men/meals/{female_only.id}").status, 404)

    def test_api_refuses_cross_path_completion(self):
        client = self._login("noa@example.com")
        male_video = content_repo.list_videos(GenderPath.MALE, limit=1)[0]
        response = client.post_json(f"/api/videos/{male_video.id}/complete")
        self.assertEqual(response.status, 404)

    def test_api_video_list_is_scoped(self):
        client = self._login("noa@example.com")
        payload = client.get("/api/videos", query={"limit": "60"}).json()
        female_titles = {video.title for video in content_repo.list_videos(GenderPath.FEMALE, limit=100)}
        for video in payload["videos"]:
            self.assertIn(video["title"], female_titles)

    def test_ai_coach_context_is_scoped(self):
        from fitness_platform.services.ai.coach import build_context_blocks
        from fitness_platform.services.auth import load_context
        from fitness_platform.services.auth import SESSION_COOKIE

        client = self._login("noa@example.com")
        context = load_context(client.cookies[SESSION_COOKIE])
        blocks = "\n".join(build_context_blocks(context, "מה האימון להיום?"))
        for video in content_repo.list_videos(GenderPath.MALE, limit=100):
            self.assertNotIn(video.title, blocks)

    def test_url_segment_alone_grants_nothing(self):
        """A member without a session cannot reach either area."""
        anonymous = self.new_client()
        for route in FEMALE_ROUTES + MALE_ROUTES:
            self.assertEqual(anonymous.get(route).status, 401, route)


class ProfileScopeTest(AppTestCase):
    def test_meal_plan_only_contains_visible_recipes(self):
        seed()
        from fitness_platform.services import meal_service

        profile = Profile.empty(2)
        plan_id = meal_service.generate_plan(2, profile, GenderPath.FEMALE)
        items = food_repo.meal_plan_items(plan_id, GenderPath.FEMALE)
        self.assertTrue(items)
        for item in items:
            self.assertNotEqual(item["recipe"].gender_path.value, "male")
