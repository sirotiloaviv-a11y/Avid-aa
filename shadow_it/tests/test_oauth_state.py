"""Tests for the signed OAuth state shared by both connect flows.

This is the only access control on the two callback endpoints — the admin's
browser arrives with no API key — so it gets tested directly rather than
through a flow.

(The provider-specific callback parsers in ``services/google_oauth.py`` and
``services/microsoft_oauth.py`` import their vendor HTTP clients at module
level, so covering those needs the full dependency set installed.)
"""

from __future__ import annotations

import base64
import json
import time
import unittest

from app.oauth_state import (
    STATE_TTL_SECONDS,
    OAuthError,
    make_state,
    verify_state,
)

SECRET = "sk_test_secret_value"
TENANT = "6f1b6f4c-0000-4000-8000-abcdefabcdef"


def _repack(tenant_id: str, issued_at: float) -> str:
    """A state body with a chosen timestamp, signed with the real secret."""
    payload = json.dumps({"t": tenant_id, "n": "nonce", "ts": int(issued_at)},
                         separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    # Reuse make_state's signer by round-tripping through a real state's format.
    from app.oauth_state import _sign

    return f"{body}.{_sign(payload, SECRET)}"


class TestSignedState(unittest.TestCase):
    def test_round_trip_returns_the_tenant(self):
        self.assertEqual(verify_state(make_state(TENANT, SECRET), SECRET), TENANT)

    def test_states_are_unique_per_call(self):
        # A replayed state should not be indistinguishable from a fresh one.
        self.assertNotEqual(make_state(TENANT, SECRET), make_state(TENANT, SECRET))

    def test_a_different_secret_is_rejected(self):
        state = make_state(TENANT, SECRET)
        with self.assertRaises(OAuthError):
            verify_state(state, "sk_some_other_secret")

    def test_tampering_with_the_tenant_id_is_rejected(self):
        # The whole point: an attacker must not be able to bind their directory
        # to someone else's tenant by editing the redirect.
        state = _repack("attacker-tenant-id", time.time())
        body, _, signature = state.partition(".")
        forged_body = base64.urlsafe_b64encode(
            json.dumps({"t": "victim-tenant-id", "n": "nonce", "ts": int(time.time())},
                       separators=(",", ":")).encode()
        ).decode().rstrip("=")
        with self.assertRaises(OAuthError):
            verify_state(f"{forged_body}.{signature}", SECRET)

    def test_expired_state_is_rejected(self):
        stale = _repack(TENANT, time.time() - STATE_TTL_SECONDS - 5)
        with self.assertRaises(OAuthError) as caught:
            verify_state(stale, SECRET)
        self.assertIn("expired", str(caught.exception))

    def test_state_just_inside_the_window_is_accepted(self):
        fresh = _repack(TENANT, time.time() - STATE_TTL_SECONDS + 30)
        self.assertEqual(verify_state(fresh, SECRET), TENANT)

    def test_malformed_states_raise_rather_than_crash(self):
        for bad in ("", "no-dot", "!!!.!!!", "a.b.c", "."):
            with self.subTest(state=bad), self.assertRaises(OAuthError):
                verify_state(bad, SECRET)


if __name__ == "__main__":
    unittest.main()
