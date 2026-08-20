"""Turn a discovered app into a defensible high / medium / low.

Design rules this follows, learned the hard way by every tool in this space:

1. **Scopes dominate.** Category and popularity adjust; access decides.
2. **Every point is explained.** ``reasons`` is the product — a band with no
   reason gets ignored, and an analyst who cannot audit the score won't trust
   the next one either.
3. **Boring apps must score boring.** If "Sign in with Google" apps land in
   medium, the customer stops reading after week one. Identity-only scopes are
   capped at low.
4. **Deterministic.** Same input, same score. No model calls, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import DiscoveredApp, RiskAssessment, RiskBand
from . import scopes as scope_lib
from .catalog import classify

# --- Weights -----------------------------------------------------------------
# Tuned so a full-Drive unknown app is high, a read-only calendar app is
# medium, and an SSO-only app is low. Every constant is named so a customer
# asking "why 74?" gets an answer instead of a shrug.
SCOPE_WEIGHT_MULTIPLIER = 6          # max scope weight 0-10 -> 0-60 points
BREADTH_POINTS_PER_SCOPE = 2         # per additional sensitive scope
BREADTH_CAP = 10
ANONYMOUS_CLIENT_POINTS = 15         # not registered in any Cloud project
NATIVE_APP_POINTS = 5                # desktop/mobile client, secret can't be kept
ADMIN_GRANT_POINTS = 15              # a super-admin authorized it
WRITE_ACCESS_POINTS = 8
WIDESPREAD_POINTS = 8                # many users, never reviewed
FOOTHOLD_POINTS = 4                  # 3+ users: past "one curious employee"
TRUSTED_DISCOUNT = -12

HIGH_THRESHOLD = 70
MEDIUM_THRESHOLD = 40

# Fractions/counts at which an unsanctioned install counts as "spreading".
WIDESPREAD_USER_COUNT = 10
WIDESPREAD_USER_FRACTION = 0.25


@dataclass
class RiskPolicy:
    """Per-tenant overrides. Everything here is customer-editable in the UI."""

    allowlisted_client_ids: set[str] = field(default_factory=set)
    blocklisted_client_ids: set[str] = field(default_factory=set)
    # Names the customer considers sanctioned, matched as substrings.
    allowlisted_keywords: set[str] = field(default_factory=set)
    high_threshold: int = HIGH_THRESHOLD
    medium_threshold: int = MEDIUM_THRESHOLD
    # Directory size, so "12 users" can be read as 3% or as 60%.
    directory_size: int = 0

    def is_allowlisted(self, app: DiscoveredApp) -> bool:
        if app.client_id in self.allowlisted_client_ids:
            return True
        name = app.display_name.lower()
        return any(kw.lower() in name for kw in self.allowlisted_keywords if kw)


def band_for(score: int, policy: RiskPolicy) -> RiskBand:
    if score >= policy.high_threshold:
        return RiskBand.HIGH
    if score >= policy.medium_threshold:
        return RiskBand.MEDIUM
    return RiskBand.LOW


def assess(app: DiscoveredApp, policy: RiskPolicy | None = None) -> RiskAssessment:
    """Score one app. Pure function: no I/O, no side effects."""
    policy = policy or RiskPolicy()
    provider = app.provider.value
    reasons: list[str] = []

    max_weight, capabilities, writes = scope_lib.summarize(app.scopes, provider)
    sensitive_count = scope_lib.count_sensitive(app.scopes, provider)
    classification = classify(app.display_name, app.client_id)
    category = classification.category

    # --- Hard decisions first, so they can't be argued down by modifiers ----
    if app.client_id in policy.blocklisted_client_ids:
        return RiskAssessment(
            score=100,
            band=RiskBand.HIGH,
            category=category.key,
            reasons=["Explicitly blocklisted by this tenant's policy."],
            capabilities=capabilities,
        )

    if policy.is_allowlisted(app):
        return RiskAssessment(
            score=0,
            band=RiskBand.LOW,
            category=category.key,
            reasons=["Allowlisted by this tenant — sanctioned application."],
            capabilities=capabilities,
        )

    # --- Score --------------------------------------------------------------
    score = max_weight * SCOPE_WEIGHT_MULTIPLIER
    if capabilities:
        reasons.append(f"Highest privilege granted: {capabilities[0]} (weight {max_weight}/10).")
    else:
        reasons.append("Only identity scopes granted (sign-in, email, profile).")

    if sensitive_count > 1:
        breadth = min(BREADTH_CAP, (sensitive_count - 1) * BREADTH_POINTS_PER_SCOPE)
        score += breadth
        reasons.append(f"Holds {sensitive_count} separate high-sensitivity scopes.")

    if writes and max_weight >= 5:
        score += WRITE_ACCESS_POINTS
        reasons.append("Has write access — it can alter or delete company data, not just read it.")

    if category.modifier:
        score += category.modifier
        reason = f"Categorized as {category.label}."
        if category.note:
            reason = f"{reason} {category.note}"
        reasons.append(reason)

    if classification.is_automation:
        reasons.append("Automation platform — data can be chained to arbitrary endpoints.")

    if app.is_anonymous:
        score += ANONYMOUS_CLIENT_POINTS
        reasons.append(
            "Client is not registered to any verified project — publisher is "
            "unverifiable, which is the strongest single Shadow IT signal."
        )

    if app.is_native_app:
        score += NATIVE_APP_POINTS
        reasons.append("Installed native/desktop client — its OAuth secret cannot be protected.")

    if app.admin_user_emails:
        score += ADMIN_GRANT_POINTS
        reasons.append(
            f"Authorized by {len(app.admin_user_emails)} privileged admin account(s) — "
            "the grant inherits admin reach."
        )

    installs = app.install_count
    fraction = installs / policy.directory_size if policy.directory_size else 0.0
    if installs >= WIDESPREAD_USER_COUNT or (fraction and fraction >= WIDESPREAD_USER_FRACTION):
        score += WIDESPREAD_POINTS
        spread = f"{installs} users"
        if fraction:
            spread += f" ({fraction:.0%} of the directory)"
        reasons.append(f"Widely installed without review: {spread}.")
    elif installs >= 3:
        score += FOOTHOLD_POINTS
        reasons.append(f"Spreading beyond one employee: {installs} users.")

    if classification.trusted:
        score += TRUSTED_DISCOUNT
        reasons.append("Known enterprise vendor — commonly procured; verify it is your account.")

    score = max(0, min(100, score))

    # --- Floors and caps ----------------------------------------------------
    # Total access to mail, Drive, the directory or the cloud project is high
    # risk regardless of who the vendor is. Being a known brand is not a
    # mitigation for "can read every file in the company".
    if max_weight >= 10:
        if score < HIGH_THRESHOLD:
            reasons.append("Floored to high: this scope grants total access to a core system.")
        score = max(score, HIGH_THRESHOLD)

    # An unverifiable publisher holding write access is high, full stop.
    if app.is_anonymous and writes and max_weight >= 7:
        if score < HIGH_THRESHOLD:
            reasons.append("Floored to high: unverified publisher holding write access.")
        score = max(score, HIGH_THRESHOLD)

    # Identity-only apps are the bulk of any inventory and are genuinely low
    # risk. Capping them is what keeps the report readable — unless the client
    # itself is unverifiable, which is worth a look on its own.
    if max_weight == 0 and not app.is_anonymous:
        score = min(score, MEDIUM_THRESHOLD - 1)
        reasons.append("Capped to low: sign-in only, no access to company data.")

    band = band_for(score, policy)
    return RiskAssessment(
        score=int(score),
        band=band,
        category=category.key,
        reasons=reasons,
        capabilities=capabilities,
    )


def assess_all(
    apps: list[DiscoveredApp], policy: RiskPolicy | None = None
) -> list[tuple[DiscoveredApp, RiskAssessment]]:
    """Score an inventory, worst first — the order you want to review it in."""
    scored = [(app, assess(app, policy)) for app in apps]
    scored.sort(key=lambda pair: (-pair[1].score, pair[0].display_name.lower()))
    return scored


def summarize_inventory(scored: list[tuple[DiscoveredApp, RiskAssessment]]) -> dict:
    """Counts for the dashboard header."""
    counts = {band.value: 0 for band in RiskBand}
    for _, assessment in scored:
        counts[assessment.band.value] += 1
    return {
        "total_apps": len(scored),
        "by_band": counts,
        "top_risks": [
            {
                "client_id": app.client_id,
                "display_name": app.display_name,
                "score": a.score,
                "band": a.band.value,
                "users": app.install_count,
            }
            for app, a in scored[:10]
        ],
    }
