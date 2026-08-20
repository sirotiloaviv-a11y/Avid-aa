"""Tests for the Microsoft 365 connector's parsing and scoring.

Run:  python -m unittest discover -s tests -t .

Everything that turns Graph's payloads into our model is a pure function, so
these run against captured response shapes — no tenant, no secret, no network.
The HTTP layer is exercised only through those shapes; what is worth testing
here is the translation, which is where the bugs actually live.
"""

from __future__ import annotations

import unittest

from app.connectors.graph_model import (
    MICROSOFT_FIRST_PARTY_TENANT,
    ServicePrincipal,
    build_grants,
    parse_user,
)
from app.connectors.base import aggregate
from app.models import (
    APPLICATION_PRINCIPAL,
    TENANT_WIDE_PRINCIPAL,
    DirectoryUser,
    GrantType,
    Provider,
    RiskBand,
)
from app.risk import RiskPolicy, assess

CUSTOMER_TENANT = "11111111-2222-3333-4444-555555555555"
GRAPH_SP_ID = "sp-graph"

# Microsoft Graph's own service principal: the only place appRole GUIDs are
# given names, which is why the connector reads appRoles off every SP.
GRAPH_SP = {
    "id": GRAPH_SP_ID,
    "appId": "00000003-0000-0000-c000-000000000000",
    "displayName": "Microsoft Graph",
    "appOwnerOrganizationId": MICROSOFT_FIRST_PARTY_TENANT,
    "servicePrincipalType": "Application",
    "accountEnabled": True,
    "appRoles": [
        {"id": "role-mail-read-all", "value": "Mail.Read.All"},
        {"id": "role-files-rw-all", "value": "Files.ReadWrite.All"},
        {"id": "role-user-read-all", "value": "User.Read.All"},
    ],
}

VERIFIED_VENDOR_SP = {
    "id": "sp-slack",
    "appId": "aaaa1111-0000-0000-0000-000000000001",
    "displayName": "Slack",
    "appOwnerOrganizationId": "9999-slack-tenant",
    "publisherName": "Slack Technologies",
    "verifiedPublisher": {"displayName": "Slack Technologies, LLC"},
    "servicePrincipalType": "Application",
    "accountEnabled": True,
}

UNVERIFIED_AI_SP = {
    "id": "sp-shadow",
    "appId": "bbbb2222-0000-0000-0000-000000000002",
    "displayName": "SuperGPT Mail Copilot",
    "appOwnerOrganizationId": "7777-someone-else",
    "verifiedPublisher": {},
    "servicePrincipalType": "Application",
    "accountEnabled": True,
}

MANAGED_IDENTITY_SP = {
    "id": "sp-mi",
    "appId": "cccc3333-0000-0000-0000-000000000003",
    "displayName": "prod-aks-identity",
    "servicePrincipalType": "ManagedIdentity",
    "accountEnabled": True,
}


def principals(*raws) -> dict[str, ServicePrincipal]:
    return {str(raw["id"]): ServicePrincipal(raw) for raw in raws}


def users(*specs) -> dict[str, DirectoryUser]:
    return {
        user_id: DirectoryUser(
            external_id=user_id, email=email, full_name=email, is_admin=is_admin
        )
        for user_id, email, is_admin in specs
    }


class TestServicePrincipal(unittest.TestCase):
    def test_microsoft_first_party_is_recognized(self):
        self.assertTrue(ServicePrincipal(GRAPH_SP).is_microsoft_first_party)
        self.assertFalse(ServicePrincipal(VERIFIED_VENDOR_SP).is_microsoft_first_party)

    def test_first_party_apps_are_out_of_scope_by_default(self):
        self.assertFalse(ServicePrincipal(GRAPH_SP).in_scope())
        self.assertTrue(ServicePrincipal(GRAPH_SP).in_scope(include_microsoft_apps=True))

    def test_managed_identities_are_never_in_scope(self):
        # Azure infrastructure, not something an employee connected.
        self.assertFalse(ServicePrincipal(MANAGED_IDENTITY_SP).in_scope())
        self.assertFalse(
            ServicePrincipal(MANAGED_IDENTITY_SP).in_scope(include_microsoft_apps=True)
        )

    def test_verified_publisher_detection(self):
        self.assertFalse(ServicePrincipal(VERIFIED_VENDOR_SP).publisher_unverified)
        self.assertTrue(ServicePrincipal(UNVERIFIED_AI_SP).publisher_unverified)

    def test_app_roles_become_an_id_to_name_map(self):
        self.assertEqual(
            ServicePrincipal(GRAPH_SP).app_roles["role-mail-read-all"], "Mail.Read.All"
        )


class TestUserParsing(unittest.TestCase):
    def test_upn_is_the_email_and_disabled_means_suspended(self):
        user = parse_user(
            {
                "id": "u1",
                "userPrincipalName": "ada@contoso.com",
                "displayName": "Ada",
                "accountEnabled": False,
                "department": "Engineering",
            },
            frozenset(),
        )
        self.assertEqual(user.email, "ada@contoso.com")
        self.assertTrue(user.is_suspended)
        self.assertEqual(user.org_unit, "Engineering")

    def test_directory_role_membership_sets_the_admin_flag(self):
        raw = {"id": "u2", "userPrincipalName": "root@contoso.com", "accountEnabled": True}
        self.assertTrue(parse_user(raw, frozenset({"u2"})).is_admin)
        self.assertFalse(parse_user(raw, frozenset({"someone-else"})).is_admin)


class TestDelegatedGrants(unittest.TestCase):
    def test_per_user_consent_resolves_the_principal(self):
        grants = build_grants(
            service_principals=principals(GRAPH_SP, UNVERIFIED_AI_SP),
            delegated_grants=[{
                "id": "g1", "clientId": "sp-shadow", "consentType": "Principal",
                "principalId": "u1", "resourceId": GRAPH_SP_ID,
                "scope": "Mail.Read User.Read",
            }],
            app_role_assignments={},
            users_by_id=users(("u1", "ada@contoso.com", False)),
        )
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0].user_email, "ada@contoso.com")
        self.assertEqual(grants[0].grant_type, GrantType.DELEGATED)
        # Graph packs permissions into one space-separated string.
        self.assertEqual(grants[0].scopes, ["Mail.Read", "User.Read"])
        # appId, not the directory-local object id — it is what Entra's UI shows.
        self.assertEqual(grants[0].client_id, UNVERIFIED_AI_SP["appId"])

    def test_admin_consent_becomes_a_tenant_wide_grant(self):
        grants = build_grants(
            service_principals=principals(UNVERIFIED_AI_SP),
            delegated_grants=[{
                "id": "g2", "clientId": "sp-shadow", "consentType": "AllPrincipals",
                "principalId": None, "scope": "Mail.Read",
            }],
            app_role_assignments={},
            users_by_id={},
        )
        self.assertEqual(grants[0].grant_type, GrantType.TENANT_WIDE)
        self.assertEqual(grants[0].user_email, TENANT_WIDE_PRINCIPAL)

    def test_admin_grant_carries_the_admin_flag(self):
        grants = build_grants(
            service_principals=principals(UNVERIFIED_AI_SP),
            delegated_grants=[{
                "clientId": "sp-shadow", "consentType": "Principal",
                "principalId": "u9", "scope": "Files.Read.All",
            }],
            app_role_assignments={},
            users_by_id=users(("u9", "root@contoso.com", True)),
        )
        self.assertTrue(grants[0].user_is_admin)

    def test_unknown_principal_is_kept_not_dropped(self):
        # Dropping evidence because a lookup missed would understate reach.
        grants = build_grants(
            service_principals=principals(UNVERIFIED_AI_SP),
            delegated_grants=[{
                "clientId": "sp-shadow", "consentType": "Principal",
                "principalId": "ghost-user-id", "scope": "Mail.Read",
            }],
            app_role_assignments={},
            users_by_id={},
        )
        self.assertEqual(len(grants), 1)
        self.assertIn("unknown principal", grants[0].user_email)

    def test_first_party_and_empty_scope_grants_are_skipped(self):
        grants = build_grants(
            service_principals=principals(GRAPH_SP, UNVERIFIED_AI_SP),
            delegated_grants=[
                {"clientId": GRAPH_SP_ID, "consentType": "AllPrincipals", "scope": "User.Read"},
                {"clientId": "sp-shadow", "consentType": "AllPrincipals", "scope": ""},
                {"clientId": "sp-missing", "consentType": "AllPrincipals", "scope": "Mail.Read"},
            ],
            app_role_assignments={},
            users_by_id={},
        )
        self.assertEqual(grants, [])


class TestApplicationPermissions(unittest.TestCase):
    def test_app_role_ids_resolve_to_permission_names(self):
        grants = build_grants(
            service_principals=principals(GRAPH_SP, UNVERIFIED_AI_SP),
            delegated_grants=[],
            app_role_assignments={
                "sp-shadow": [
                    {"id": "a1", "appRoleId": "role-mail-read-all", "resourceId": GRAPH_SP_ID},
                    {"id": "a2", "appRoleId": "role-files-rw-all", "resourceId": GRAPH_SP_ID},
                ]
            },
            users_by_id={},
        )
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0].grant_type, GrantType.APPLICATION)
        self.assertEqual(grants[0].user_email, APPLICATION_PRINCIPAL)
        self.assertEqual(grants[0].scopes, ["Files.ReadWrite.All", "Mail.Read.All"])

    def test_unresolvable_app_role_is_reported_not_hidden(self):
        grants = build_grants(
            service_principals=principals(UNVERIFIED_AI_SP),
            delegated_grants=[],
            app_role_assignments={
                "sp-shadow": [{"id": "a1", "appRoleId": "role-from-another-api"}]
            },
            users_by_id={},
        )
        self.assertIn("unknown app role", grants[0].scopes[0])


class TestAggregationAndScoring(unittest.TestCase):
    def _shadow_app(self, delegated, assignments):
        grants = build_grants(
            service_principals=principals(GRAPH_SP, UNVERIFIED_AI_SP, VERIFIED_VENDOR_SP),
            delegated_grants=delegated,
            app_role_assignments=assignments,
            users_by_id=users(
                ("u1", "ada@contoso.com", False),
                ("u2", "bob@contoso.com", False),
            ),
        )
        apps = aggregate(grants, Provider.MICROSOFT)
        return {app.client_id: app for app in apps}[UNVERIFIED_AI_SP["appId"]]

    def test_synthetic_principals_do_not_inflate_the_user_count(self):
        app = self._shadow_app(
            delegated=[
                {"clientId": "sp-shadow", "consentType": "Principal",
                 "principalId": "u1", "scope": "Mail.Read"},
                {"clientId": "sp-shadow", "consentType": "AllPrincipals", "scope": "Mail.Read"},
            ],
            assignments={"sp-shadow": [{"id": "a", "appRoleId": "role-mail-read-all"}]},
        )
        # One real person, even though three grant rows exist.
        self.assertEqual(app.install_count, 1)
        self.assertTrue(app.tenant_wide_consent)
        self.assertTrue(app.has_application_permissions)

    def test_tenant_wide_consent_scores_above_the_same_single_user_grant(self):
        single = self._shadow_app(
            delegated=[{"clientId": "sp-shadow", "consentType": "Principal",
                        "principalId": "u1", "scope": "Calendars.Read"}],
            assignments={},
        )
        everyone = self._shadow_app(
            delegated=[{"clientId": "sp-shadow", "consentType": "AllPrincipals",
                        "scope": "Calendars.Read"}],
            assignments={},
        )
        self.assertGreater(assess(everyone).score, assess(single).score)

    def test_app_only_access_to_a_sensitive_api_is_high(self):
        app = self._shadow_app(
            delegated=[],
            assignments={"sp-shadow": [{"id": "a", "appRoleId": "role-mail-read-all"}]},
        )
        result = assess(app)
        self.assertEqual(result.band, RiskBand.HIGH)
        self.assertTrue(any("app-only" in reason for reason in result.reasons))

    def test_unverified_publisher_flows_through_to_the_score(self):
        app = self._shadow_app(
            delegated=[{"clientId": "sp-shadow", "consentType": "Principal",
                        "principalId": "u1", "scope": "Files.ReadWrite.All"}],
            assignments={},
        )
        self.assertTrue(app.is_anonymous)
        self.assertEqual(assess(app).band, RiskBand.HIGH)

    def test_sign_in_only_entra_app_stays_low(self):
        grants = build_grants(
            service_principals=principals(VERIFIED_VENDOR_SP),
            delegated_grants=[{"clientId": "sp-slack", "consentType": "Principal",
                               "principalId": "u1", "scope": "User.Read openid profile"}],
            app_role_assignments={},
            users_by_id=users(("u1", "ada@contoso.com", False)),
        )
        app = aggregate(grants, Provider.MICROSOFT)[0]
        self.assertEqual(assess(app).band, RiskBand.LOW)

    def test_tenant_wide_sign_in_only_app_is_not_capped_to_low(self):
        # Sign-in scopes are harmless; consenting for the whole directory
        # without anyone asking is still worth a look.
        grants = build_grants(
            service_principals=principals(VERIFIED_VENDOR_SP),
            delegated_grants=[{"clientId": "sp-slack", "consentType": "AllPrincipals",
                               "scope": "User.Read"}],
            app_role_assignments={},
            users_by_id={},
        )
        app = aggregate(grants, Provider.MICROSOFT)[0]
        result = assess(app)
        self.assertTrue(any("entire directory" in reason for reason in result.reasons))

    def test_allowlist_still_wins_for_entra_apps(self):
        app = self._shadow_app(
            delegated=[],
            assignments={"sp-shadow": [{"id": "a", "appRoleId": "role-mail-read-all"}]},
        )
        policy = RiskPolicy(allowlisted_client_ids={app.client_id})
        self.assertEqual(assess(app, policy).band, RiskBand.LOW)


if __name__ == "__main__":
    unittest.main()
