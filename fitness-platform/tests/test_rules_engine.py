"""Personalisation rules: the hard filters and the ranking (18, 20)."""

from __future__ import annotations

from .helpers import AppTestCase

from fitness_platform.db.repositories import content as content_repo, food as food_repo
from fitness_platform.db.seed import seed
from fitness_platform.domain.gender import GenderPath
from fitness_platform.domain.models import Profile, Recipe, Video
from fitness_platform.domain.rules_engine import (
    rank_recipes,
    rank_videos,
    recipe_is_allowed,
    score_program,
    score_recipe,
    score_video,
)
from fitness_platform.services import meal_service, program_service


def make_video(**overrides) -> Video:
    row = {
        "id": 1, "title": "t", "description": "", "thumbnail_url": "", "video_url": "",
        "duration": 30, "difficulty": "beginner", "category": "full_body",
        "gender_path": "female", "coach_id": None, "equipment": "[]", "tags": "[]", "published": 1,
    }
    row.update(overrides)
    return Video.from_row(row)


def make_recipe(**overrides) -> Recipe:
    row = {
        "id": 1, "name": "מתכון", "description": "", "ingredients": "[]", "instructions": "[]",
        "image_url": "", "tags": "[]", "meal_type": "lunch", "dietary_tags": "[]",
        "allergens": "[]", "gender_path": "all", "prep_minutes": 15, "approved": 1,
    }
    row.update(overrides)
    return Recipe.from_row(row)


class VideoRulesTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.profile = Profile.empty(1)
        self.profile.equipment = ["mat"]
        self.profile.session_minutes = 30
        self.profile.experience_level = "beginner"

    def test_unpublished_is_never_a_candidate(self):
        self.assertIsNone(score_video(self.profile, make_video(published=0)))

    def test_missing_equipment_excludes(self):
        self.assertIsNone(score_video(self.profile, make_video(equipment='["barbell"]')))

    def test_gym_membership_satisfies_any_equipment(self):
        self.profile.equipment = ["gym"]
        self.assertIsNotNone(score_video(self.profile, make_video(equipment='["barbell"]')))

    def test_two_levels_above_is_excluded(self):
        self.assertIsNone(score_video(self.profile, make_video(difficulty="advanced")))

    def test_one_level_above_is_allowed(self):
        self.assertIsNotNone(score_video(self.profile, make_video(difficulty="intermediate")))

    def test_matching_duration_scores_higher(self):
        near = score_video(self.profile, make_video(id=1, duration=30))
        far = score_video(self.profile, make_video(id=2, duration=60))
        self.assertGreater(near, far)

    def test_goal_bonus_applies(self):
        self.profile.goals = ["posture"]
        stretch = score_video(self.profile, make_video(id=1, category="stretch"))
        upper = score_video(self.profile, make_video(id=2, category="upper_body"))
        self.assertGreater(stretch, upper)

    def test_ranking_is_deterministic(self):
        videos = [make_video(id=index, duration=30) for index in range(1, 6)]
        first = [video.id for video in rank_videos(self.profile, videos)]
        second = [video.id for video in rank_videos(self.profile, list(reversed(videos)))]
        self.assertEqual(first, second)


class RecipeRulesTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.profile = Profile.empty(1)

    def test_unapproved_recipes_are_never_served(self):
        self.assertFalse(recipe_is_allowed(self.profile, make_recipe(approved=0)))

    def test_allergen_is_a_hard_exclusion(self):
        self.profile.allergies = ["nuts"]
        self.assertFalse(recipe_is_allowed(self.profile, make_recipe(allergens='["nuts"]')))

    def test_allergen_exclusion_is_case_insensitive(self):
        self.profile.allergies = ["NUTS"]
        self.assertFalse(recipe_is_allowed(self.profile, make_recipe(allergens='["nuts"]')))

    def test_strict_diet_requires_a_matching_tag(self):
        self.profile.dietary_tags = ["vegan"]
        self.assertFalse(recipe_is_allowed(self.profile, make_recipe(dietary_tags='["vegetarian"]')))
        self.assertTrue(recipe_is_allowed(self.profile, make_recipe(dietary_tags='["vegan"]')))

    def test_soft_preference_does_not_exclude(self):
        self.profile.dietary_tags = ["high_protein"]
        self.assertTrue(recipe_is_allowed(self.profile, make_recipe(dietary_tags='[]')))

    def test_disliked_ingredient_excludes(self):
        self.profile.disliked_foods = ["חציל"]
        recipe = make_recipe(ingredients='[{"name": "חציל", "amount": "1"}]')
        self.assertFalse(recipe_is_allowed(self.profile, recipe))

    def test_quick_recipes_rank_higher(self):
        quick = score_recipe(self.profile, make_recipe(id=1, prep_minutes=10))
        slow = score_recipe(self.profile, make_recipe(id=2, prep_minutes=60))
        self.assertGreater(quick, slow)

    def test_rank_drops_excluded_recipes(self):
        self.profile.allergies = ["dairy"]
        recipes = [make_recipe(id=1, allergens='["dairy"]'), make_recipe(id=2)]
        self.assertEqual([r.id for r in rank_recipes(self.profile, recipes)], [2])


class ProgramRulesTest(AppTestCase):
    def setUp(self):
        super().setUp()
        seed(with_demo_users=False)
        self.profile = Profile.empty(1)
        self.profile.equipment = ["mat"]
        self.profile.goals = ["tone", "routine"]

    def test_recommendation_matches_the_path(self):
        program = program_service.recommended_program(self.profile, GenderPath.FEMALE)
        self.assertIsNotNone(program)
        self.assertNotEqual(program.gender_path.value, "male")

    def test_goal_overlap_raises_the_score(self):
        programs = content_repo.list_programs(GenderPath.FEMALE)
        scores = {program.name: score_program(self.profile, program) for program in programs}
        self.assertEqual(max(scores, key=scores.get), "מסלול התחלה לנשים")

    def test_preview_is_read_only(self):
        from fitness_platform.db.repositories import users as users_repo

        user_id = users_repo.create_user("preview@example.com", "x", gender_path=GenderPath.FEMALE)
        preview = program_service.build_preview(self.profile, GenderPath.FEMALE)
        self.assertIsNotNone(preview.program)
        self.assertIsNone(content_repo.active_program_id(user_id))


class MealPlanTest(AppTestCase):
    def setUp(self):
        super().setUp()
        seed(with_demo_users=False)
        from fitness_platform.db.repositories import users as users_repo

        self.user_id = users_repo.create_user(
            "planner@example.com", "x", name="בודקת", gender_path=GenderPath.FEMALE
        )
        self.profile = Profile.empty(self.user_id)

    def test_plan_covers_seven_days(self):
        plan_id = meal_service.generate_plan(self.user_id, self.profile, GenderPath.FEMALE)
        days = meal_service.plan_days(plan_id, GenderPath.FEMALE)
        self.assertEqual(len([index for index, items in days.items() if items]), 7)

    def test_allergies_never_reach_the_plan(self):
        self.profile.allergies = ["nuts", "dairy"]
        plan_id = meal_service.generate_plan(self.user_id, self.profile, GenderPath.FEMALE)
        for item in food_repo.meal_plan_items(plan_id, GenderPath.FEMALE):
            self.assertNotIn("nuts", item["recipe"].allergens)
            self.assertNotIn("dairy", item["recipe"].allergens)

    def test_replacement_picks_a_different_recipe(self):
        plan_id = meal_service.generate_plan(self.user_id, self.profile, GenderPath.FEMALE)
        items = meal_service.plan_days(plan_id, GenderPath.FEMALE)[0]
        original = items[0]
        replacement = meal_service.replace_meal(
            plan_id, self.profile, GenderPath.FEMALE, 0, original["meal_type"], original["recipe"].id
        )
        self.assertIsNotNone(replacement)
        self.assertNotEqual(replacement.id, original["recipe"].id)

    def test_shopping_list_merges_duplicates(self):
        plan_id = meal_service.generate_plan(self.user_id, self.profile, GenderPath.FEMALE)
        list_id = meal_service.build_shopping_list(self.user_id, plan_id, GenderPath.FEMALE)
        items = food_repo.list_shopping_items(list_id)
        names = [item["name"] for item in items]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(any("×" in item["amount"] for item in items))

    def test_shopping_items_are_categorised(self):
        plan_id = meal_service.generate_plan(self.user_id, self.profile, GenderPath.FEMALE)
        list_id = meal_service.build_shopping_list(self.user_id, plan_id, GenderPath.FEMALE)
        categories = {item["category"] for item in food_repo.list_shopping_items(list_id)}
        self.assertTrue(categories - {"other"})
