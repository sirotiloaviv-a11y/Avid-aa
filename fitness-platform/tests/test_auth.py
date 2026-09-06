"""Accounts, sessions, CSRF and rate limiting (3, 34)."""

from __future__ import annotations

from .helpers import AppTestCase

from fitness_platform.core.errors import Conflict, RateLimited, Unauthorized, ValidationError
from fitness_platform.db.repositories import users as users_repo
from fitness_platform.domain.gender import GenderPath
from fitness_platform.domain.roles import Permission, Role, has_permission
from fitness_platform.services import auth
from fitness_platform.services.security import hash_password, limiter, needs_rehash, verify_password


class PasswordTest(AppTestCase):
    def test_hash_round_trip(self):
        stored = hash_password("correct horse")
        self.assertTrue(verify_password("correct horse", stored))
        self.assertFalse(verify_password("wrong horse", stored))

    def test_hashes_are_salted(self):
        self.assertNotEqual(hash_password("same"), hash_password("same"))

    def test_malformed_hash_is_rejected_not_crashed(self):
        self.assertFalse(verify_password("x", ""))
        self.assertFalse(verify_password("x", "garbage"))
        self.assertFalse(verify_password("x", "md5$1$aa$bb"))

    def test_needs_rehash_on_weaker_parameters(self):
        self.assertTrue(needs_rehash("pbkdf2_sha256$10$aa$bb"))
        self.assertFalse(needs_rehash(hash_password("x")))


class RegistrationTest(AppTestCase):
    def test_register_creates_profile_and_path(self):
        user = auth.register("a@b.co", "secret123", "נועה כהן", GenderPath.FEMALE)
        self.assertEqual(user.gender_path, GenderPath.FEMALE)
        self.assertEqual(user.role, Role.USER)
        self.assertIsNotNone(users_repo.get_profile(user.id))

    def test_duplicate_email_conflicts(self):
        auth.register("a@b.co", "secret123", "נועה", GenderPath.FEMALE)
        with self.assertRaises(Conflict):
            auth.register("A@B.co", "secret123", "אחרת", GenderPath.FEMALE)

    def test_validation_errors(self):
        with self.assertRaises(ValidationError) as caught:
            auth.register("not-an-email", "123", "x", GenderPath.MALE)
        self.assertIn("email", caught.exception.errors)
        self.assertIn("password", caught.exception.errors)
        self.assertIn("name", caught.exception.errors)

    def test_wrong_password_is_unauthorized(self):
        auth.register("a@b.co", "secret123", "נועה", GenderPath.FEMALE)
        with self.assertRaises(Unauthorized):
            auth.authenticate("a@b.co", "nope1234")

    def test_unknown_email_is_unauthorized(self):
        with self.assertRaises(Unauthorized):
            auth.authenticate("ghost@b.co", "secret123")

    def test_login_attempts_are_rate_limited(self):
        auth.register("a@b.co", "secret123", "נועה", GenderPath.FEMALE)
        limiter.reset()
        failures = 0
        for _ in range(40):
            try:
                auth.authenticate("a@b.co", "wrong-one", ip_address="9.9.9.9")
            except RateLimited:
                break
            except Unauthorized:
                failures += 1
        else:
            self.fail("rate limiter never engaged")
        self.assertLess(failures, 40)


class SessionTest(AppTestCase):
    def test_signup_starts_a_session(self):
        response = self.client.signup("women", "a@b.co")
        self.assertEqual(response.status, 303)
        self.assertEqual(response.location, "/onboarding")
        self.assertIn(auth.SESSION_COOKIE, self.client.cookies)

    def test_session_cookie_is_http_only_and_same_site(self):
        response = self.client.signup("men", "m@b.co")
        cookie = [value for key, value in response.headers if key.lower() == "set-cookie"][0]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)

    def test_logout_clears_the_session(self):
        self.client.signup("women", "a@b.co")
        self.client.logout()
        self.assertEqual(self.client.get("/onboarding").status, 401)

    def test_gender_path_cannot_be_changed_by_a_second_signup_route(self):
        self.client.signup("women", "a@b.co")
        user = users_repo.get_user_by_email("a@b.co")
        users_repo.set_gender_path(user.id, GenderPath.MALE)  # one-way setter
        self.assertEqual(users_repo.get_user(user.id).gender_path, GenderPath.FEMALE)

    def test_password_change_invalidates_sessions(self):
        self.client.signup("women", "a@b.co")
        user = users_repo.get_user_by_email("a@b.co")
        auth.change_password(user, "secret123", "brand-new-1")
        self.assertEqual(self.client.get("/onboarding").status, 401)


class CsrfTest(AppTestCase):
    def test_post_without_token_is_rejected(self):
        self.client.signup("women", "a@b.co")
        response = self.client.request("POST", "/onboarding/0", data={"display_name": "נועה"})
        self.assertEqual(response.status, 403)

    def test_post_with_wrong_token_is_rejected(self):
        self.client.signup("women", "a@b.co")
        response = self.client.request(
            "POST", "/onboarding/0", data={"display_name": "נועה", "csrf_token": "forged"}
        )
        self.assertEqual(response.status, 403)

    def test_post_with_token_is_accepted(self):
        self.client.signup("women", "a@b.co")
        response = self.client.post(
            "/onboarding/0", {"display_name": "נועה", "birth_year": "1994"}
        )
        self.assertEqual(response.status, 303)


class RoleTest(AppTestCase):
    def test_user_has_no_admin_permissions(self):
        self.assertFalse(has_permission(Role.USER, Permission.MANAGE_USERS))
        self.assertFalse(has_permission(Role.USER, Permission.MANAGE_CONTENT))
        self.assertTrue(has_permission(Role.USER, Permission.USE_APP))

    def test_admin_has_every_permission(self):
        for permission in Permission:
            self.assertTrue(has_permission(Role.ADMIN, permission))

    def test_unknown_role_falls_back_to_user(self):
        self.assertIs(Role.parse("wizard"), Role.USER)


class SecurityHeaderTest(AppTestCase):
    def test_headers_are_present_on_every_response(self):
        response = self.client.get("/")
        self.assertEqual(response.header("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.header("X-Frame-Options"), "DENY")
        self.assertIn("default-src 'self'", response.header("Content-Security-Policy"))
        self.assertIn("frame-ancestors 'none'", response.header("Content-Security-Policy"))

    def test_authenticated_pages_are_not_cached(self):
        self.client.signup("women", "a@b.co")
        self.assertEqual(self.client.get("/onboarding/0").header("Cache-Control"), "no-store")

    def test_static_assets_are_served(self):
        response = self.client.get("/static/css/tokens.css")
        self.assertEqual(response.status, 200)
        self.assertIn("text/css", response.header("Content-Type"))

    def test_static_path_traversal_is_blocked(self):
        self.assertEqual(self.client.get("/static/../config.py").status, 404)
