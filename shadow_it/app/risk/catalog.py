"""What kind of app is this, and does anyone vouch for it?

Two independent signals feed the score:

* **Category** — an AI note-taker with mailbox access is a different problem
  from a payroll vendor with the same access, because nobody procured the
  note-taker and nobody knows where the data lands.
* **Trust** — a short list of vendors that are almost always sanctioned. This
  only *dampens* the score; a trusted vendor asking for full Drive still ranks.

Matching is on the display name and the client id, both lowercased. That is
deliberately fuzzy: Shadow IT shows up under names like "Otter.ai for Chrome",
not under a stable identifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    modifier: int          # added to the raw score
    keywords: tuple[str, ...] = ()
    note: str = ""


# Order matters: the first matching category wins, so specific beats generic.
# "Otter.ai" must land in meeting_ai, not in the broader ai bucket whose
# ".ai"/"gpt" keywords are deliberately greedy.
CATEGORIES: tuple[Category, ...] = (
    Category(
        "meeting_ai", "AI meeting recorder", 20,
        ("otter", "fireflies", "fathom", "grain.com", "tldv", "avoma", "sembly",
         "read.ai", "supernormal", "notetaker", "meetgeek", "circleback"),
        "Joins meetings and stores transcripts of everything said.",
    ),
    Category(
        "ai", "AI / LLM tool", 18,
        (
            "chatgpt", "openai", "claude", "anthropic", "gemini", "perplexity",
            "copilot", "jasper", "writesonic", "copy.ai", "midjourney",
            "huggingface", "replicate", "mistral", "deepseek", "poe.com",
            " ai ", "ai-", "-ai", ".ai", "gpt", "llm", "prompt",
        ),
        "Employee data may be leaving the tenant into a model provider.",
    ),
    Category(
        "remote_access", "Remote access / RMM", 18,
        ("teamviewer", "anydesk", "rustdesk", "splashtop", "screenconnect",
         "logmein", "remote desktop", "gotoassist", "ngrok", "tailscale",
         "chrome remote"),
        "Grants an outside party interactive access to endpoints.",
    ),
    Category(
        "file_sharing", "File sharing / storage", 15,
        ("dropbox", "box.com", "wetransfer", "mega.nz", "sync.com", "pcloud",
         "smallpdf", "ilovepdf", "pdffiller", "sejda", "zamzar", "filestage",
         "sendgb", "transfer", "backup", "migrat", "export", "cloudconvert"),
        "Bulk-moves company files to storage outside the tenant.",
    ),
    Category(
        "dev_tools", "Developer tool", 12,
        ("github", "gitlab", "bitbucket", "replit", "vercel", "netlify",
         "render.com", "heroku", "railway", "postman", "insomnia", "cursor",
         "codeium", "tabnine", "sourcegraph", "circleci", "jenkins", "sentry",
         "docker", "terraform", "apps script", "script.google"),
        "Often self-onboarded by engineers and wired into production.",
    ),
    Category(
        "browser_ext", "Browser extension", 12,
        ("extension", "for chrome", "chrome web store", "add-on", "addon",
         "toolbar", "plugin for"),
        "Extensions change hands and update silently after install.",
    ),
    Category(
        "email_marketing", "Email / outreach tool", 12,
        ("mailchimp", "sendgrid", "lemlist", "apollo.io", "outreach.io",
         "salesloft", "instantly", "snov", "hunter.io", "mailtrack",
         "yesware", "mixmax", "streak", "gmass", "boomerang", "mail merge",
         "unroll"),
        "Reads or sends from employee mailboxes at volume.",
    ),
    Category(
        "crm_sales", "CRM / sales", 6,
        ("salesforce", "hubspot", "pipedrive", "zoho", "close.com", "copper",
         "freshsales", "gong.io", "chorus.ai", "clari"),
    ),
    Category(
        "security", "Security / IT tooling", 0,
        ("okta", "jumpcloud", "1password", "bitwarden", "lastpass", "duo",
         "crowdstrike", "sentinelone", "proofpoint", "mimecast", "knowbe4",
         "vanta", "drata", "secureframe", "wiz.io", "cloudflare"),
        "Usually procured by IT — verify it is yours before dismissing it.",
    ),
    Category(
        "productivity", "Productivity / SaaS", 5,
        ("slack", "zoom", "atlassian", "jira", "confluence", "notion", "asana",
         "monday.com", "clickup", "trello", "airtable", "miro", "figma",
         "calendly", "docusign", "loom", "linear.app", "zapier", "make.com",
         "workato", "ifttt"),
    ),
    Category("unknown", "Unclassified", 8, (), "No vendor match — treat as unvetted."),
)

CATEGORY_BY_KEY = {c.key: c for c in CATEGORIES}
UNKNOWN = CATEGORY_BY_KEY["unknown"]

# Vendors a tech company almost certainly did procure on purpose. This is a
# dampener, never an exemption — see engine.TRUSTED_DISCOUNT.
TRUSTED_VENDOR_KEYWORDS: frozenset[str] = frozenset({
    "slack", "zoom", "atlassian", "jira", "confluence", "salesforce",
    "hubspot", "okta", "jumpcloud", "1password", "docusign", "figma",
    "notion", "asana", "github", "gitlab", "zapier", "calendly", "loom",
    "dropbox", "box.com", "workday", "netsuite", "sentry", "datadog",
    "pagerduty", "cloudflare", "adobe", "microsoft", "apple inc",
})

# Automation platforms deserve their own flag: the risk is not the platform,
# it is that anyone can wire it to anything without review.
AUTOMATION_KEYWORDS: frozenset[str] = frozenset({
    "zapier", "make.com", "integromat", "ifttt", "workato", "tray.io",
    "n8n", "pipedream", "apps script",
})


@dataclass
class Classification:
    category: Category
    trusted: bool = False
    is_automation: bool = False
    matched_on: str = ""
    notes: list[str] = field(default_factory=list)


def _haystack(display_name: str, client_id: str) -> str:
    # Pad with spaces so " ai " style keywords can match at the edges.
    return f" {display_name.lower().strip()} | {client_id.lower().strip()} "


def classify(display_name: str, client_id: str = "") -> Classification:
    """Best-effort category for an app. Never raises, never returns None."""
    hay = _haystack(display_name, client_id)

    matched_category = UNKNOWN
    matched_on = ""
    for category in CATEGORIES:
        hit = next((kw for kw in category.keywords if kw in hay), None)
        if hit:
            matched_category, matched_on = category, hit
            break

    trusted = any(kw in hay for kw in TRUSTED_VENDOR_KEYWORDS)
    automation = any(kw in hay for kw in AUTOMATION_KEYWORDS)

    notes: list[str] = []
    if matched_category.note:
        notes.append(matched_category.note)
    if automation:
        notes.append("Automation platform — can chain company data to any endpoint.")

    return Classification(
        category=matched_category,
        trusted=trusted,
        is_automation=automation,
        matched_on=matched_on,
        notes=notes,
    )
