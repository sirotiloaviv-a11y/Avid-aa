"""Questionnaire validation, persistence and resumption (7, 8, 11)."""

from __future__ import annotations

from .helpers import AppTestCase

from fitness_platform.db.repositories import onboarding as onboarding_repo, users as users_repo
from fitness_platform.domain.gender import GenderPath
from fitness_platform.domain.onboarding import (
    profile_updates,
    step_count,
    steps_for,
    validate_step,
)

STEP_PAYLOADS = [
    {"display_name": "נועה", "birth_year": "1994", "height_cm": "168", "weight_kg": "62"},
    {"experience_level": "beginner", "weekly_frequency": "3", "session_minutes": "30"},
    {"equipment": ["mat", "bands"]},
    {"goals": ["tone", "energy"], "workout_style": ["pilates"]},
    {"dietary_tags": ["vegetarian"], "allergies": ["nuts"], "meals_per_day": "3", "disliked_foods": "חציל, טופו"},
    {"preferred_days": ["sun", "tue", "thu"], "preferred_time": "evening"},
]


def complete_questionnaire(client):
    for index, payload in enumerate(STEP_PAYLOADS):
        client.post(f"/onboarding/{index}", payload)


class QuestionDefinitionTest(AppTestCase):
    def test_both_paths_have_steps(self):
        self.assertEqual(step_count(GenderPath.FEMALE), step_count(GenderPath.MALE))
        self.assertGreaterEqual(step_count(GenderPath.FEMALE), 5)

    def test_goal_options_differ_between_paths(self):
        female_goals = {
            option.value
            for step in steps_for(GenderPath.FEMALE)
            for question in step.questions
            if question.key == "goals"
            for option in question.options
        }
        male_goals = {
            option.value
            for step in steps_for(GenderPath.MALE)
            for question in step.questions
            if question.key == "goals"
            for option in question.options
        }
        self.assertNotEqual(female_goals, male_goals)

    def test_every_question_key_is_unique_per_path(self):
        for path in (GenderPath.FEMALE, GenderPath.MALE):
            keys = [question.key for step in steps_for(path) for question in step.questions]
            self.assertEqual(len(keys), len(set(keys)))


class ValidationTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.steps = steps_for(GenderPath.FEMALE)

    def test_required_single_choice_must_be_a_known_option(self):
        cleaned, errors = validate_step(self.steps[1], {"experience_level": ["hacker"]})
        self.assertIn("experience_level", errors)
        self.assertNotIn("experience_level", cleaned)

    def test_numbers_are_range_checked(self):
        _, errors = validate_step(self.steps[0], {"display_name": ["נועה"], "birth_year": ["1200"]})
        self.assertIn("birth_year", errors)

    def test_non_numeric_number_is_rejected(self):
        _, errors = validate_step(self.steps[0], {"display_name": ["נועה"], "birth_year": ["שנה"]})
        self.assertIn("birth_year", errors)

    def test_multi_choice_respects_max(self):
        goals_step = self.steps[3]
        _, errors = validate_step(goals_step, {"goals": ["tone", "strength", "weight", "posture"]})
        self.assertIn("goals", errors)

    def test_unknown_multi_values_are_dropped(self):
        cleaned, errors = validate_step(self.steps[2], {"equipment": ["mat", "spaceship"]})
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["equipment"], ["mat"])

    def test_optional_fields_may_be_blank(self):
        cleaned, errors = validate_step(
            self.steps[0], {"display_name": ["נועה"], "birth_year": ["1990"], "height_cm": [""], "weight_kg": [""]}
        )
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["height_cm"], "")

    def test_profile_projection_types(self):
        cleaned, _ = validate_step(self.steps[1], {"experience_level": ["beginner"], "weekly_frequency": ["4"], "session_minutes": ["45"]})
        updates = profile_updates(GenderPath.FEMALE, cleaned)
        self.assertEqual(updates["weekly_frequency"], 4)
        self.assertIsInstance(updates["session_minutes"], int)


class FlowTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.client.signup("women", "a@b.co")
        self.user = users_repo.get_user_by_email("a@b.co")

    def test_entry_redirects_to_first_step(self):
        response = self.client.get("/onboarding")
        self.assertEqual(response.location, "/onboarding/0")

    def test_progress_is_saved_between_steps(self):
        self.client.post("/onboarding/0", STEP_PAYLOADS[0])
        answers = onboarding_repo.get_answers(self.user.id)
        self.assertEqual(answers["display_name"], "נועה")
        self.assertEqual(onboarding_repo.get_progress(self.user.id)["current_step"], 1)

    def test_returning_member_resumes_where_they_stopped(self):
        self.client.post("/onboarding/0", STEP_PAYLOADS[0])
        self.client.post("/onboarding/1", STEP_PAYLOADS[1])
        fresh = self.new_client()
        fresh.login("a@b.co")
        self.assertEqual(fresh.get("/onboarding").location, "/onboarding/2")

    def test_going_back_keeps_earlier_answers(self):
        self.client.post("/onboarding/0", STEP_PAYLOADS[0])
        self.client.post("/onboarding/1", STEP_PAYLOADS[1])
        page = self.client.get("/onboarding/0")
        self.assertIn('value="נועה"', page.text)

    def test_invalid_step_rerenders_with_the_submitted_values(self):
        response = self.client.post("/onboarding/0", {"display_name": "דנה", "birth_year": "abc"})
        self.assertEqual(response.status, 200)
        self.assertIn("צריך להזין מספר", response.text)
        self.assertIn('value="דנה"', response.text)

    def test_answers_reach_the_profile(self):
        complete_questionnaire(self.client)
        profile = users_repo.get_profile(self.user.id)
        self.assertEqual(profile.experience_level, "beginner")
        self.assertEqual(profile.equipment, ["mat", "bands"])
        self.assertIn("nuts", profile.allergies)
        self.assertEqual(profile.disliked_foods, ["חציל", "טופו"])

    def test_completion_leads_to_the_plan_preview(self):
        complete_questionnaire(self.client)
        self.assertTrue(users_repo.get_user(self.user.id).onboarding_completed)
        ready = self.client.get("/onboarding/ready")
        self.assertEqual(ready.status, 200)
        self.assertIn("התוכנית שלך מוכנה", ready.text)

    def test_preview_is_reachable_without_paying_but_the_app_is_not(self):
        complete_questionnaire(self.client)
        self.assertEqual(self.client.get("/onboarding/ready").status, 200)
        blocked = self.client.get("/women/dashboard")
        self.assertEqual(blocked.status, 403)

    def test_out_of_range_step_redirects(self):
        self.assertEqual(self.client.get("/onboarding/99").location, "/onboarding")
