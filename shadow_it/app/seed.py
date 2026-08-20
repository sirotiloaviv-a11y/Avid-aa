"""Demo data for local development.

Without this you cannot see the dashboard without pointing the stack at a real
Workspace or Entra tenant, which is a lot to ask before the first screenshot.

The seed does *not* fabricate scores. It builds ``DiscoveredApp`` objects and
pushes them through the same risk engine and the same repository writes a real
scan uses, so what you see locally is what the product would actually have
produced from those grants — and the seed doubles as an end-to-end exercise of
the engine and the persistence layer.

    python -m app.main --seed-demo

Safe to re-run: every write is an upsert keyed the same way a scan's would be.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .models import (
    APPLICATION_PRINCIPAL,
    TENANT_WIDE_PRINCIPAL,
    AppGrant,
    DirectoryUser,
    DiscoveredApp,
    GrantType,
    Provider,
)
from .risk import assess_all

if TYPE_CHECKING:  # keeps this module importable (and testable) without asyncpg
    from .services.repository import Repository

log = logging.getLogger(__name__)

DEMO_TENANT_NAME = "Northwind Robotics"
DEMO_TENANT_DOMAIN = "northwind.example"

# A directory big enough that "18 of them" reads as a share of the company.
DEMO_PEOPLE: tuple[tuple[str, str, bool], ...] = (
    ("ada.lovelace", "Ada Lovelace", True),      # IT admin
    ("grace.hopper", "Grace Hopper", True),      # IT admin
    ("alan.turing", "Alan Turing", False),
    ("katherine.johnson", "Katherine Johnson", False),
    ("linus.pauling", "Linus Pauling", False),
    ("rosalind.franklin", "Rosalind Franklin", False),
    ("james.west", "James West", False),
    ("mai.tran", "Mai Tran", False),
    ("omar.haddad", "Omar Haddad", False),
    ("sofia.rossi", "Sofia Rossi", False),
    ("nia.okafor", "Nia Okafor", False),
    ("erik.lund", "Erik Lund", False),
)
DEMO_DIRECTORY_SIZE = 48  # the company is bigger than the sample above


@dataclass
class DemoApp:
    """One app as a scan would have observed it."""

    name: str
    client_id: str
    provider: Provider
    scopes: list[str]
    users: int = 1
    admins: int = 0
    anonymous: bool = False
    native: bool = False
    tenant_wide: bool = False
    app_only: bool = False
    note: str = field(default="")


G = "https://www.googleapis.com/auth/"

DEMO_APPS: tuple[DemoApp, ...] = (
    # --- Google Workspace ------------------------------------------------
    DemoApp(
        "Sign in with Google — Figma", "figma.apps.googleusercontent.com", Provider.GOOGLE,
        ["openid", "email", G + "userinfo.profile"], users=11,
        note="The identity-only tail every inventory has. Must score low.",
    ),
    DemoApp(
        "Slack", "slack-prod.apps.googleusercontent.com", Provider.GOOGLE,
        [G + "userinfo.email", G + "drive.file", G + "calendar.readonly"], users=12,
        note="Sanctioned vendor, narrow scopes.",
    ),
    DemoApp(
        "Calendly", "calendly.apps.googleusercontent.com", Provider.GOOGLE,
        [G + "calendar", G + "userinfo.email"], users=9,
    ),
    DemoApp(
        "Grammarly for Chrome", "grammarly-ext.apps.googleusercontent.com", Provider.GOOGLE,
        [G + "drive.file", G + "userinfo.email"], users=7, native=True,
    ),
    DemoApp(
        "Otter.ai Meeting Notes", "otterai.apps.googleusercontent.com", Provider.GOOGLE,
        [G + "calendar.readonly", G + "drive.file", G + "userinfo.email"], users=6,
        note="AI note-taker: sits in meetings, keeps the transcript.",
    ),
    DemoApp(
        "WeTransfer Drive Sync", "wetransfer-sync.apps.googleusercontent.com", Provider.GOOGLE,
        [G + "drive.readonly"], users=4,
        note="Bulk-reads Drive to somewhere outside the tenant.",
    ),
    DemoApp(
        "Zapier", "zapier.apps.googleusercontent.com", Provider.GOOGLE,
        [G + "drive", G + "spreadsheets", G + "gmail.modify"], users=3, admins=1,
        note="Automation platform, full Drive, and an admin granted it.",
    ),
    DemoApp(
        "SuperGPT Mail Assistant", "482913740021-superg.apps.googleusercontent.com",
        Provider.GOOGLE, ["https://mail.google.com/", G + "contacts.readonly"], users=2,
        anonymous=True,
        note="Unverified publisher with the full mailbox. The headline finding.",
    ),
    DemoApp(
        "nw-provisioning-script", "nw-internal-script.apps.googleusercontent.com",
        Provider.GOOGLE,
        [G + "admin.directory.user", G + "admin.reports.audit.readonly"],
        users=1, admins=1, anonymous=True,
        note="Somebody's internal script holding directory write.",
    ),
    # --- Microsoft 365 ----------------------------------------------------
    DemoApp(
        "1Password Business", "aaaa1111-0000-4000-8000-00000000one", Provider.MICROSOFT,
        ["User.Read", "openid", "profile"], users=10,
    ),
    DemoApp(
        "Adobe Acrobat", "aaaa1111-0000-4000-8000-00000000two", Provider.MICROSOFT,
        ["Files.ReadWrite", "User.Read"], users=8,
    ),
    DemoApp(
        "Fireflies.ai Notetaker", "bbbb2222-0000-4000-8000-000000fireflies",
        Provider.MICROSOFT, ["Calendars.Read", "User.Read.All"], users=0, tenant_wide=True,
        note="Admin-consented for everyone. Nobody opted in, so: zero users, "
             "whole company.",
    ),
    DemoApp(
        "Contoso Invoice Sync", "cccc3333-0000-4000-8000-0000000invoice",
        Provider.MICROSOFT, ["Mail.Read.All", "Files.ReadWrite.All"], users=0,
        app_only=True, anonymous=True,
        note="App-only mail and file access, unverified publisher.",
    ),
    DemoApp(
        "ShadowSync Backup", "dddd4444-0000-4000-8000-00000shadowsync",
        Provider.MICROSOFT, ["Sites.FullControl.All", "Files.ReadWrite.All"], users=0,
        app_only=True, tenant_wide=True, anonymous=True,
        note="Every Entra red flag at once.",
    ),
)


def _people() -> list[DirectoryUser]:
    return [
        DirectoryUser(
            external_id=f"demo-user-{index}",
            email=f"{handle}@{DEMO_TENANT_DOMAIN}",
            full_name=name,
            is_admin=is_admin,
            org_unit="/Engineering" if index % 2 else "/Operations",
        )
        for index, (handle, name, is_admin) in enumerate(DEMO_PEOPLE)
    ]


def _to_app(demo: DemoApp, people: list[DirectoryUser]) -> tuple[DiscoveredApp, list[AppGrant]]:
    """Build the app the way ``aggregate`` would, from synthetic grants."""
    app = DiscoveredApp(
        client_id=demo.client_id, display_name=demo.name, provider=demo.provider
    )
    grants: list[AppGrant] = []

    admins = [p for p in people if p.is_admin][: demo.admins]
    others = [p for p in people if not p.is_admin][: max(0, demo.users - len(admins))]
    for person in [*admins, *others]:
        grants.append(
            AppGrant(
                client_id=demo.client_id,
                display_name=demo.name,
                user_email=person.email,
                scopes=list(demo.scopes),
                is_anonymous=demo.anonymous,
                is_native_app=demo.native,
                user_is_admin=person.is_admin,
                grant_type=GrantType.DELEGATED,
            )
        )

    if demo.tenant_wide:
        grants.append(
            AppGrant(
                client_id=demo.client_id, display_name=demo.name,
                user_email=TENANT_WIDE_PRINCIPAL, scopes=list(demo.scopes),
                is_anonymous=demo.anonymous, grant_type=GrantType.TENANT_WIDE,
            )
        )
    if demo.app_only:
        grants.append(
            AppGrant(
                client_id=demo.client_id, display_name=demo.name,
                user_email=APPLICATION_PRINCIPAL, scopes=list(demo.scopes),
                is_anonymous=demo.anonymous, grant_type=GrantType.APPLICATION,
            )
        )

    for grant in grants:
        app.absorb(grant)
    return app, grants


async def seed_demo(repo: "Repository") -> dict:
    """Create the demo tenant and its inventory. Idempotent."""
    tenant = await repo.create_tenant(
        name=DEMO_TENANT_NAME,
        primary_domain=DEMO_TENANT_DOMAIN,
        contact_email=f"it@{DEMO_TENANT_DOMAIN}",
        plan="demo",
    )
    tenant_id = str(tenant["id"])

    people = _people()
    user_ids = await repo.upsert_users(tenant_id, people, Provider.GOOGLE)
    # The engine reads install counts as a share of the directory, so the
    # headcount has to be set before anything is scored.
    await repo.set_directory_size(tenant_id, DEMO_DIRECTORY_SIZE)
    policy = await repo.load_policy(tenant_id)

    written = 0
    for provider in (Provider.GOOGLE, Provider.MICROSOFT):
        demos = [d for d in DEMO_APPS if d.provider is provider]
        if not demos:
            continue
        scan_id = await repo.start_scan(tenant_id, provider, trigger_kind="seed")

        built = [_to_app(demo, people) for demo in demos]
        scored = assess_all([app for app, _ in built], policy)
        grants_by_client = {app.client_id: grants for app, grants in built}

        grant_count = 0
        new_apps = 0
        for app, assessment in scored:
            outcome = await repo.upsert_app(tenant_id, app, assessment, scan_id)
            grants = grants_by_client.get(app.client_id, [])
            await repo.upsert_grants(tenant_id, outcome["app_id"], grants, user_ids)
            grant_count += len(grants)
            new_apps += 1 if outcome["is_new"] else 0
            written += 1

        await repo.finish_scan(
            scan_id,
            "success",
            users_scanned=len(people),
            grants_found=grant_count,
            apps_found=len(scored),
            # Zero on a re-seed, which is correct: nothing was newly discovered.
            new_apps=new_apps,
        )

    log.info("Seeded demo tenant %s with %d apps", tenant_id, written)
    return {"tenant_id": tenant_id, "apps": written, "domain": DEMO_TENANT_DOMAIN}
