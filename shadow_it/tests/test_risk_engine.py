"""Tests for the risk engine.

Run:  python -m unittest discover -s shadow_it/tests -t shadow_it

These need no database and no Google credentials — the engine is a pure
function, which is the main reason it was written as one.
"""

from __future__ import annotations

import unittest

from app.models import AppGrant, DiscoveredApp, Provider, RiskBand
from app.risk import RiskPolicy, assess, classify, describe_scope

G = "https://www.googleapis.com/auth/"


def make_app(
    name: str,
    scopes: list[str],
    users: int = 1,
    anonymous: bool = False,
    native: bool = False,
    admins: int = 0,
) -> DiscoveredApp:
    app = DiscoveredApp(
        client_id=f"{abs(hash(name)) % 10**12}.apps.googleusercontent.com",
        display_name=name,
        provider=Provider.GOOGLE,
        is_anonymous=anonymous,
        is_native_app=native,
    )
    for i in range(users):
        app.absorb(
            AppGrant(
                client_id=app.client_id,
                display_name=name,
                user_email=f"user{i}@example.com",
                scopes=scopes,
                is_anonymous=anonymous,
                is_native_app=native,
                user_is_admin=i < admins,
            )
        )
    return app


class TestScopeWeights(unittest.TestCase):
    def test_full_mailbox_is_maximal(self):
        self.assertEqual(describe_scope("https://mail.google.com/").weight, 10)

    def test_drive_file_is_not_treated_like_full_drive(self):
        limited = describe_scope(G + "drive.file").weight
        full = describe_scope(G + "drive").weight
        self.assertLess(limited, full)

    def test_identity_scopes_are_zero(self):
        for scope in ("openid", "email", G + "userinfo.email"):
            self.assertEqual(describe_scope(scope).weight, 0, scope)

    def test_unknown_scope_is_not_assumed_harmless(self):
        self.assertGreater(describe_scope(G + "something.brand.new").weight, 0)

    def test_longest_prefix_wins(self):
        # admin.directory.* must not fall through to the softer admin.* rule.
        directory = describe_scope(G + "admin.directory.device.chromeos")
        generic = describe_scope(G + "admin.somethingelse")
        self.assertGreater(directory.weight, generic.weight)

    def test_microsoft_scopes_resolve(self):
        self.assertEqual(describe_scope("Files.ReadWrite.All", "microsoft").weight, 10)


class TestClassification(unittest.TestCase):
    def test_ai_tool_detected_by_name(self):
        self.assertEqual(classify("ChatGPT for Google").category.key, "ai")

    def test_meeting_recorder_beats_generic_ai(self):
        self.assertEqual(classify("Otter.ai Notetaker").category.key, "meeting_ai")

    def test_trusted_vendor_flagged(self):
        self.assertTrue(classify("Slack").trusted)

    def test_unknown_app_is_unclassified_not_crash(self):
        result = classify("", "")
        self.assertEqual(result.category.key, "unknown")


class TestRiskBands(unittest.TestCase):
    def test_sso_only_app_is_low(self):
        app = make_app("Some Login App", ["openid", "email", G + "userinfo.profile"])
        self.assertEqual(assess(app).band, RiskBand.LOW)

    def test_unverified_ai_tool_with_mail_access_is_high(self):
        app = make_app("SuperGPT Mail Assistant", ["https://mail.google.com/"], anonymous=True)
        result = assess(app)
        self.assertEqual(result.band, RiskBand.HIGH)
        self.assertTrue(any("unverifiable" in r or "not registered" in r for r in result.reasons))

    def test_full_drive_is_high_even_for_a_trusted_vendor(self):
        app = make_app("Slack", [G + "drive"])
        self.assertEqual(assess(app).band, RiskBand.HIGH)

    def test_read_only_calendar_app_is_not_high(self):
        app = make_app("Team Calendar Viewer", [G + "calendar.readonly"])
        self.assertNotEqual(assess(app).band, RiskBand.HIGH)

    def test_file_sharing_tool_scores_above_equivalent_productivity_tool(self):
        sharing = assess(make_app("WeTransfer Uploader", [G + "drive.readonly"]))
        generic = assess(make_app("Acme Timesheets", [G + "drive.readonly"]))
        self.assertGreater(sharing.score, generic.score)

    def test_admin_grant_raises_score(self):
        scopes = [G + "calendar"]
        without = assess(make_app("Booking Tool", scopes, users=2))
        with_admin = assess(make_app("Booking Tool", scopes, users=2, admins=1))
        self.assertGreater(with_admin.score, without.score)

    def test_widespread_install_raises_score(self):
        scopes = [G + "spreadsheets.readonly"]
        few = assess(make_app("Report Sync", scopes, users=1))
        many = assess(make_app("Report Sync", scopes, users=25))
        self.assertGreater(many.score, few.score)

    def test_directory_write_access_is_high(self):
        app = make_app("Internal Provisioning Script", [G + "admin.directory.user"])
        self.assertEqual(assess(app).band, RiskBand.HIGH)

    def test_score_is_bounded(self):
        app = make_app(
            "Everything Bagel",
            ["https://mail.google.com/", G + "drive", G + "admin.directory.user",
             G + "cloud-platform"],
            users=50, anonymous=True, native=True, admins=5,
        )
        result = assess(app)
        self.assertLessEqual(result.score, 100)
        self.assertGreaterEqual(result.score, 0)

    def test_every_assessment_explains_itself(self):
        app = make_app("Anything", [G + "drive.readonly"])
        self.assertTrue(assess(app).reasons)


class TestPolicy(unittest.TestCase):
    def test_allowlisted_app_drops_to_low(self):
        app = make_app("Approved Backup Tool", [G + "drive"])
        policy = RiskPolicy(allowlisted_client_ids={app.client_id})
        result = assess(app, policy)
        self.assertEqual(result.band, RiskBand.LOW)
        self.assertEqual(result.score, 0)

    def test_blocklisted_app_is_always_high(self):
        app = make_app("Banned Thing", ["openid"])
        policy = RiskPolicy(blocklisted_client_ids={app.client_id})
        self.assertEqual(assess(app, policy).band, RiskBand.HIGH)

    def test_keyword_allowlist_matches_display_name(self):
        app = make_app("Acme Internal Sync", [G + "drive"])
        policy = RiskPolicy(allowlisted_keywords={"acme internal"})
        self.assertEqual(assess(app, policy).band, RiskBand.LOW)

    def test_small_company_reads_ten_users_as_widespread(self):
        scopes = [G + "spreadsheets.readonly"]
        big = assess(make_app("Sheet Sync", scopes, users=6), RiskPolicy(directory_size=1000))
        small = assess(make_app("Sheet Sync", scopes, users=6), RiskPolicy(directory_size=12))
        self.assertGreater(small.score, big.score)


class TestAggregation(unittest.TestCase):
    def test_grants_collapse_into_one_app(self):
        app = make_app("Shared Tool", [G + "calendar"], users=4, admins=1)
        self.assertEqual(app.install_count, 4)
        self.assertEqual(len(app.admin_user_emails), 1)

    def test_scopes_union_across_users(self):
        app = DiscoveredApp(client_id="c1", display_name="Mixed")
        app.absorb(AppGrant("c1", "Mixed", "a@example.com", [G + "calendar"]))
        app.absorb(AppGrant("c1", "Mixed", "b@example.com", [G + "drive.readonly"]))
        self.assertEqual(app.scopes, {G + "calendar", G + "drive.readonly"})


if __name__ == "__main__":
    unittest.main()


class TestDemoInventory(unittest.TestCase):
    """The seeded demo data has a job: show what the product is for.

    If every demo app lands in one band, the local dashboard demonstrates
    nothing — so the shape of that inventory is worth asserting.
    """

    def setUp(self):
        from app.risk import assess_all
        from app.seed import DEMO_APPS, DEMO_DIRECTORY_SIZE, _people, _to_app

        people = _people()
        apps = [_to_app(demo, people)[0] for demo in DEMO_APPS]
        self.scored = dict(
            (app.display_name, assessment)
            for app, assessment in assess_all(apps, RiskPolicy(directory_size=DEMO_DIRECTORY_SIZE))
        )

    def test_all_three_bands_are_represented(self):
        bands = {a.band for a in self.scored.values()}
        self.assertEqual(bands, {RiskBand.HIGH, RiskBand.MEDIUM, RiskBand.LOW})

    def test_the_headline_findings_are_high(self):
        for name in (
            "SuperGPT Mail Assistant",     # unverified publisher, full mailbox
            "nw-provisioning-script",      # internal script with directory write
            "Contoso Invoice Sync",        # app-only mail and file access
            "ShadowSync Backup",           # every Entra flag at once
        ):
            with self.subTest(app=name):
                self.assertEqual(self.scored[name].band, RiskBand.HIGH)

    def test_the_boring_apps_stay_boring(self):
        self.assertEqual(self.scored["Sign in with Google — Figma"].band, RiskBand.LOW)
        self.assertEqual(self.scored["1Password Business"].band, RiskBand.LOW)

    def test_both_providers_are_present(self):
        from app.models import Provider
        from app.seed import DEMO_APPS

        self.assertEqual(
            {d.provider for d in DEMO_APPS}, {Provider.GOOGLE, Provider.MICROSOFT}
        )
