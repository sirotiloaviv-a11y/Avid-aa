"""What an OAuth scope actually lets an app do.

Scope strings are the only reliable evidence of blast radius: an app's name can
lie, its scopes cannot. Each entry is (weight 0-10, human-readable capability,
writes?). Weight 10 means "this app can read or destroy the business".

Unlisted scopes are not treated as harmless — see UNKNOWN_SCOPE_WEIGHT.
"""

from __future__ import annotations

from dataclasses import dataclass

UNKNOWN_SCOPE_WEIGHT = 5


@dataclass(frozen=True)
class ScopeInfo:
    weight: int
    capability: str
    writes: bool = False


G = "https://www.googleapis.com/auth/"

# Exact matches win over prefix matches below.
GOOGLE_SCOPES: dict[str, ScopeInfo] = {
    # --- Identity only: the "Sign in with Google" tail of any inventory ----
    "openid": ScopeInfo(0, "Sign-in identity"),
    "email": ScopeInfo(0, "Email address"),
    "profile": ScopeInfo(0, "Basic profile"),
    G + "userinfo.email": ScopeInfo(0, "Email address"),
    G + "userinfo.profile": ScopeInfo(0, "Basic profile"),
    # --- Gmail ------------------------------------------------------------
    "https://mail.google.com/": ScopeInfo(10, "Full mailbox: read, send, delete", True),
    G + "gmail.modify": ScopeInfo(9, "Read and modify all mail", True),
    G + "gmail.readonly": ScopeInfo(8, "Read all mail"),
    G + "gmail.settings.sharing": ScopeInfo(9, "Change forwarding and delegation", True),
    G + "gmail.settings.basic": ScopeInfo(8, "Change filters and auto-forwarding", True),
    G + "gmail.compose": ScopeInfo(7, "Compose and send as the user", True),
    G + "gmail.send": ScopeInfo(7, "Send mail as the user", True),
    G + "gmail.insert": ScopeInfo(6, "Insert mail into the mailbox", True),
    G + "gmail.labels": ScopeInfo(3, "Manage labels", True),
    G + "gmail.metadata": ScopeInfo(6, "Read message headers and recipients"),
    # --- Drive ------------------------------------------------------------
    G + "drive": ScopeInfo(10, "Full Drive: read, edit, delete, share", True),
    G + "drive.readonly": ScopeInfo(8, "Read every file in Drive"),
    G + "drive.metadata": ScopeInfo(5, "Read and edit file metadata", True),
    G + "drive.metadata.readonly": ScopeInfo(4, "Read file and folder names"),
    G + "drive.file": ScopeInfo(2, "Only files the user explicitly picks", True),
    G + "drive.appdata": ScopeInfo(2, "Its own hidden app folder", True),
    G + "drive.scripts": ScopeInfo(8, "Modify Apps Script files", True),
    # --- Docs / Sheets / Slides -------------------------------------------
    G + "documents": ScopeInfo(7, "Read and edit all Docs", True),
    G + "documents.readonly": ScopeInfo(6, "Read all Docs"),
    G + "spreadsheets": ScopeInfo(7, "Read and edit all Sheets", True),
    G + "spreadsheets.readonly": ScopeInfo(6, "Read all Sheets"),
    G + "presentations": ScopeInfo(6, "Read and edit all Slides", True),
    # --- Calendar / Contacts / Chat ---------------------------------------
    G + "calendar": ScopeInfo(6, "Read and edit calendars", True),
    G + "calendar.events": ScopeInfo(6, "Read and edit events", True),
    G + "calendar.readonly": ScopeInfo(5, "Read calendars, including guests"),
    G + "contacts": ScopeInfo(7, "Read and edit contacts", True),
    G + "contacts.readonly": ScopeInfo(6, "Read all contacts"),
    G + "directory.readonly": ScopeInfo(6, "Read the company directory"),
    G + "chat.messages": ScopeInfo(7, "Read and send Chat messages", True),
    G + "chat.messages.readonly": ScopeInfo(6, "Read Chat messages"),
    # --- Admin / infrastructure: nothing above this ------------------------
    G + "admin.directory.user": ScopeInfo(10, "Create and modify user accounts", True),
    G + "admin.directory.user.security": ScopeInfo(10, "Manage user tokens and 2SV", True),
    G + "admin.directory.group": ScopeInfo(10, "Manage groups and membership", True),
    G + "admin.directory.user.readonly": ScopeInfo(8, "Read every user account"),
    G + "admin.directory.group.readonly": ScopeInfo(7, "Read all groups"),
    G + "admin.reports.audit.readonly": ScopeInfo(7, "Read admin and login audit logs"),
    G + "admin.datatransfer": ScopeInfo(9, "Transfer data between users", True),
    G + "apps.groups.settings": ScopeInfo(8, "Change group access settings", True),
    G + "cloud-platform": ScopeInfo(10, "Full Google Cloud project access", True),
    G + "devstorage.read_write": ScopeInfo(8, "Read and write Cloud Storage", True),
    G + "script.external_request": ScopeInfo(8, "Apps Script calling external URLs", True),
    G + "script.scriptapp": ScopeInfo(8, "Apps Script installing its own triggers", True),
}

# Longest-prefix fallback for the long tail (e.g. every ``admin.directory.*``
# variant Google adds next quarter still lands in the right band).
GOOGLE_SCOPE_PREFIXES: tuple[tuple[str, ScopeInfo], ...] = (
    (G + "admin.directory.", ScopeInfo(9, "Directory administration", True)),
    (G + "admin.", ScopeInfo(8, "Workspace administration", True)),
    (G + "gmail.", ScopeInfo(8, "Mailbox access", True)),
    (G + "drive.", ScopeInfo(7, "Drive access", True)),
    (G + "cloud-", ScopeInfo(9, "Google Cloud access", True)),
    (G + "devstorage.", ScopeInfo(7, "Cloud Storage access", True)),
    (G + "script.", ScopeInfo(7, "Apps Script execution", True)),
    (G + "chat.", ScopeInfo(6, "Google Chat access", True)),
    (G + "calendar.", ScopeInfo(5, "Calendar access", True)),
    (G + "contacts.", ScopeInfo(6, "Contacts access", True)),
)

# Microsoft Graph, for the M365 connector. Graph permissions are already
# human-readable, and the ``.All`` suffix is the tenant-wide tell: Mail.Read is
# one mailbox, Mail.Read.All is every mailbox in the company.
#
# One caveat worth knowing: the *same* permission name is worth more as an
# application permission than as a delegated one, because app-only access needs
# no signed-in user. The engine handles that difference, not this table.
MICROSOFT_SCOPES: dict[str, ScopeInfo] = {
    # --- Identity only ----------------------------------------------------
    "User.Read": ScopeInfo(0, "Sign-in identity"),
    "openid": ScopeInfo(0, "Sign-in identity"),
    "email": ScopeInfo(0, "Email address"),
    "profile": ScopeInfo(0, "Basic profile"),
    "offline_access": ScopeInfo(1, "Long-lived refresh token"),
    # --- Directory and tenant control: nothing above this -----------------
    "Directory.ReadWrite.All": ScopeInfo(10, "Full directory write", True),
    "Directory.Read.All": ScopeInfo(8, "Read the whole directory"),
    "RoleManagement.ReadWrite.Directory": ScopeInfo(10, "Assign directory roles", True),
    "AppRoleAssignment.ReadWrite.All": ScopeInfo(10, "Grant itself any permission", True),
    "Application.ReadWrite.All": ScopeInfo(10, "Create and modify app registrations", True),
    "Policy.ReadWrite.ConditionalAccess": ScopeInfo(10, "Rewrite conditional access", True),
    "User.ReadWrite.All": ScopeInfo(9, "Create and modify every user", True),
    "User.Read.All": ScopeInfo(7, "Read every user profile"),
    "Group.ReadWrite.All": ScopeInfo(8, "Manage all groups and membership", True),
    "DeviceManagementConfiguration.ReadWrite.All": ScopeInfo(9, "Rewrite Intune policy", True),
    "AuditLog.Read.All": ScopeInfo(7, "Read sign-in and audit logs"),
    # --- Mail -------------------------------------------------------------
    "Mail.ReadWrite": ScopeInfo(9, "Read and write mailbox", True),
    "Mail.ReadWrite.All": ScopeInfo(10, "Read and write every mailbox", True),
    "Mail.Read": ScopeInfo(8, "Read mailbox"),
    "Mail.Read.All": ScopeInfo(10, "Read every mailbox in the tenant"),
    "Mail.Send": ScopeInfo(7, "Send mail as the user", True),
    "MailboxSettings.ReadWrite": ScopeInfo(9, "Change forwarding and rules", True),
    "full_access_as_app": ScopeInfo(10, "Full access to every mailbox (EWS)", True),
    # --- Files and sites --------------------------------------------------
    "Files.ReadWrite.All": ScopeInfo(10, "Read and write all files", True),
    "Files.Read.All": ScopeInfo(8, "Read all files"),
    "Files.ReadWrite": ScopeInfo(7, "Read and write the user's files", True),
    "Sites.FullControl.All": ScopeInfo(10, "Full control of all SharePoint sites", True),
    "Sites.ReadWrite.All": ScopeInfo(9, "Read and write all SharePoint sites", True),
    "Sites.Read.All": ScopeInfo(8, "Read all SharePoint sites"),
    # --- Teams, calendar, contacts ---------------------------------------
    "Chat.Read.All": ScopeInfo(9, "Read every Teams chat"),
    "ChannelMessage.Read.All": ScopeInfo(9, "Read every Teams channel message"),
    "Calendars.ReadWrite": ScopeInfo(6, "Read and write calendars", True),
    "Calendars.Read": ScopeInfo(5, "Read calendars, including attendees"),
    "Contacts.Read": ScopeInfo(6, "Read contacts"),
    "People.Read.All": ScopeInfo(6, "Read the relationship graph"),
}

MICROSOFT_SCOPE_PREFIXES: tuple[tuple[str, ScopeInfo], ...] = (
    ("Directory.", ScopeInfo(9, "Directory access", True)),
    ("RoleManagement.", ScopeInfo(10, "Role assignment", True)),
    ("AppRoleAssignment.", ScopeInfo(10, "Permission granting", True)),
    ("Application.", ScopeInfo(10, "App registration control", True)),
    ("Policy.", ScopeInfo(9, "Tenant policy control", True)),
    ("DeviceManagement", ScopeInfo(8, "Intune device management", True)),
    ("Mail.", ScopeInfo(8, "Mailbox access", True)),
    ("MailboxSettings.", ScopeInfo(8, "Mailbox settings", True)),
    ("Files.", ScopeInfo(8, "File access", True)),
    ("Sites.", ScopeInfo(8, "SharePoint access", True)),
    ("Chat.", ScopeInfo(7, "Teams chat access", True)),
    ("ChannelMessage.", ScopeInfo(8, "Teams channel messages", True)),
    ("Team", ScopeInfo(7, "Teams access", True)),
    ("Group.", ScopeInfo(7, "Group access", True)),
    ("User.", ScopeInfo(6, "User profile access", True)),
    ("Calendars.", ScopeInfo(5, "Calendar access", True)),
    ("Contacts.", ScopeInfo(6, "Contacts access", True)),
)

_READ_ONLY_HINTS = (".readonly", ".read", "_read", ".metadata.readonly")

# Graph suffix meaning "every object of this type in the tenant", not just the
# signed-in user's. It is the single most important modifier in a Graph
# permission name, so a prefix match must not lose it.
_MICROSOFT_TENANT_WIDE_SUFFIX = ".All"


def describe_scope(scope: str, provider: str = "google") -> ScopeInfo:
    """Resolve one scope to its blast radius. Never returns None."""
    scope = scope.strip()
    if not scope:
        return ScopeInfo(0, "empty scope")

    exact, prefixes = (
        (MICROSOFT_SCOPES, MICROSOFT_SCOPE_PREFIXES)
        if provider == "microsoft"
        else (GOOGLE_SCOPES, GOOGLE_SCOPE_PREFIXES)
    )
    if scope in exact:
        return exact[scope]

    # Longest prefix wins, so admin.directory. beats admin.
    best: ScopeInfo | None = None
    best_len = -1
    for prefix, info in prefixes:
        if scope.startswith(prefix) and len(prefix) > best_len:
            best, best_len = info, len(prefix)
    if best is not None:
        if provider == "microsoft" and scope.endswith(_MICROSOFT_TENANT_WIDE_SUFFIX):
            # Mail.Read is one mailbox; Mail.Read.All is the whole company.
            return ScopeInfo(
                min(10, best.weight + 1), best.capability + " (tenant-wide)", best.writes
            )
        if any(hint in scope.lower() for hint in _READ_ONLY_HINTS):
            return ScopeInfo(max(0, best.weight - 1), best.capability + " (read-only)", False)
        return best

    # Unknown scope: assume moderate rather than harmless. A scope we have
    # never seen is, if anything, evidence of an unusual app.
    return ScopeInfo(UNKNOWN_SCOPE_WEIGHT, f"Unrecognized scope ({scope})", False)


def summarize(scopes: list[str] | set[str], provider: str = "google") -> tuple[int, list[str], bool]:
    """Return (max weight, deduped capability list, any-write) for a scope set."""
    max_weight = 0
    writes = False
    capabilities: list[str] = []
    seen: set[str] = set()
    for info in sorted(
        (describe_scope(s, provider) for s in scopes), key=lambda i: i.weight, reverse=True
    ):
        max_weight = max(max_weight, info.weight)
        writes = writes or info.writes
        if info.capability not in seen and info.weight > 0:
            seen.add(info.capability)
            capabilities.append(info.capability)
    return max_weight, capabilities, writes


def count_sensitive(scopes: list[str] | set[str], provider: str = "google", floor: int = 7) -> int:
    return sum(1 for s in scopes if describe_scope(s, provider).weight >= floor)
