"""Billing lifecycle and the rule that only a webhook grants access (10, 45)."""

from __future__ import annotations

import json

from .helpers import AppTestCase

from fitness_platform.core.errors import BadRequest
from fitness_platform.db.repositories import billing as billing_repo, users as users_repo
from fitness_platform.domain.subscription import PLANS, SubscriptionStatus, get_plan
from fitness_platform.services.payments import billing_service
from fitness_platform.services.payments.factory import get_provider
from fitness_platform.services.payments.mock_provider import SIGNATURE_HEADER
from .test_onboarding import complete_questionnaire


class PlanTest(AppTestCase):
    def test_plans_are_addressable_by_code(self):
        for plan in PLANS:
            self.assertIs(get_plan(plan.code), plan)
        self.assertIsNone(get_plan("free-forever"))

    def test_status_access_matrix(self):
        self.assertTrue(SubscriptionStatus.ACTIVE.grants_access)
        self.assertTrue(SubscriptionStatus.CANCELLED.grants_access)  # until the period ends
        self.assertFalse(SubscriptionStatus.PENDING.grants_access)
        self.assertFalse(SubscriptionStatus.PAST_DUE.grants_access)
        self.assertFalse(SubscriptionStatus.EXPIRED.grants_access)


class WebhookTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.client.signup("women", "a@b.co")
        complete_questionnaire(self.client)
        self.user = users_repo.get_user_by_email("a@b.co")
        self.client.post("/subscribe", {"plan": "monthly"})
        self.subscription = billing_repo.latest_subscription(self.user.id)

    def test_checkout_creates_a_pending_subscription(self):
        self.assertIs(self.subscription.status, SubscriptionStatus.PENDING)
        self.assertFalse(self.subscription.is_active)

    def test_pending_subscription_does_not_open_the_app(self):
        self.assertEqual(self.client.get("/women/dashboard").status, 403)

    def test_valid_webhook_activates(self):
        provider = get_provider()
        body, headers = provider.build_event("payment.succeeded", self.subscription.provider_ref, 14900)
        self.assertEqual(billing_service.handle_webhook(headers, body), "activated")
        refreshed = billing_repo.latest_subscription(self.user.id)
        self.assertIs(refreshed.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(self.client.get("/women/dashboard").status, 200)

    def test_forged_signature_is_rejected(self):
        provider = get_provider()
        body, _ = provider.build_event("payment.succeeded", self.subscription.provider_ref, 14900)
        with self.assertRaises(BadRequest):
            billing_service.handle_webhook({SIGNATURE_HEADER: "0" * 64}, body)
        self.assertIs(billing_repo.latest_subscription(self.user.id).status, SubscriptionStatus.PENDING)

    def test_tampered_body_is_rejected(self):
        provider = get_provider()
        body, headers = provider.build_event("payment.succeeded", self.subscription.provider_ref, 14900)
        payload = json.loads(body)
        payload["amount_cents"] = 1
        with self.assertRaises(BadRequest):
            billing_service.handle_webhook(headers, json.dumps(payload).encode())

    def test_replayed_event_is_a_no_op(self):
        provider = get_provider()
        body, headers = provider.build_event("payment.succeeded", self.subscription.provider_ref, 14900)
        billing_service.handle_webhook(headers, body)
        self.assertEqual(billing_service.handle_webhook(headers, body), "duplicate")
        payments = billing_repo.recent_payments(10)
        self.assertEqual(len([p for p in payments if p["status"] == "succeeded"]), 1)

    def test_failed_payment_marks_past_due(self):
        provider = get_provider()
        body, headers = provider.build_event("payment.failed", self.subscription.provider_ref, 14900)
        billing_service.handle_webhook(headers, body)
        self.assertIs(billing_repo.latest_subscription(self.user.id).status, SubscriptionStatus.PAST_DUE)
        self.assertEqual(self.client.get("/women/dashboard").status, 403)

    def test_unknown_reference_is_acknowledged_not_applied(self):
        provider = get_provider()
        body, headers = provider.build_event("payment.succeeded", "ref-that-does-not-exist", 14900)
        self.assertEqual(billing_service.handle_webhook(headers, body), "unknown_subscription")

    def test_unknown_event_type_is_ignored(self):
        provider = get_provider()
        body, headers = provider.build_event("invoice.doodled", self.subscription.provider_ref, 100)
        self.assertEqual(billing_service.handle_webhook(headers, body), "ignored")

    def test_webhook_endpoint_accepts_a_signed_post(self):
        provider = get_provider()
        body, headers = provider.build_event("payment.succeeded", self.subscription.provider_ref, 14900)
        response = self.client.request(
            "POST", "/api/payments/webhook", json_body=json.loads(body),
            headers={SIGNATURE_HEADER: headers[SIGNATURE_HEADER]},
        )
        self.assertEqual(response.status, 200)

    def test_webhook_endpoint_rejects_an_unsigned_post(self):
        response = self.client.request("POST", "/api/payments/webhook", json_body={"id": "1", "type": "payment.succeeded", "provider_ref": "x"})
        self.assertEqual(response.status, 400)


class CheckoutFlowTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.client.signup("men", "m@b.co")
        complete_questionnaire(self.client)
        self.user = users_repo.get_user_by_email("m@b.co")

    def test_full_purchase_opens_the_app(self):
        redirect = self.client.post("/subscribe", {"plan": "yearly"})
        self.assertIn("/billing/checkout/", redirect.location)
        page = self.client.get(redirect.location)
        self.assertEqual(page.status, 200)
        self.assertNotIn("מספר כרטיס", page.text)  # no fake card form (50)
        subscription_id = billing_repo.latest_subscription(self.user.id).id
        self.client.post(f"/billing/checkout/{subscription_id}", {"outcome": "success"})
        self.assertEqual(self.client.get("/men/dashboard").status, 200)

    def test_another_members_checkout_is_not_reachable(self):
        self.client.post("/subscribe", {"plan": "monthly"})
        subscription_id = billing_repo.latest_subscription(self.user.id).id
        intruder = self.new_client()
        intruder.signup("women", "intruder@b.co")
        self.assertEqual(intruder.get(f"/billing/checkout/{subscription_id}").status, 404)

    def test_cancellation_keeps_access_until_the_period_ends(self):
        self.client.post("/subscribe", {"plan": "monthly"})
        subscription_id = billing_repo.latest_subscription(self.user.id).id
        self.client.post(f"/billing/checkout/{subscription_id}", {"outcome": "success"})
        self.client.post("/men/settings/cancel")
        subscription = billing_repo.latest_subscription(self.user.id)
        self.assertIs(subscription.status, SubscriptionStatus.CANCELLED)
        self.assertTrue(subscription.is_active)
        self.assertEqual(self.client.get("/men/dashboard").status, 200)

    def test_expired_period_closes_access(self):
        self.client.post("/subscribe", {"plan": "monthly"})
        subscription_id = billing_repo.latest_subscription(self.user.id).id
        self.client.post(f"/billing/checkout/{subscription_id}", {"outcome": "success"})
        from fitness_platform.db.connection import execute

        execute(
            "UPDATE subscriptions SET current_period_end = '2020-01-01T00:00:00' WHERE id = ?",
            (subscription_id,),
        )
        self.assertEqual(self.client.get("/men/dashboard").status, 403)
        self.assertIs(billing_repo.latest_subscription(self.user.id).status, SubscriptionStatus.EXPIRED)

    def test_settings_stay_reachable_without_an_active_subscription(self):
        self.assertEqual(self.client.get("/men/settings").status, 200)
