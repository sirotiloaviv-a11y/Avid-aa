# Architecture and the decisions behind it

This document records the choices that are not obvious from reading the code,
and the reasoning that would otherwise be lost.

## 1. Stack: standard library only

**Decision.** The application is a PEP 3333 WSGI app written against the Python
3.11 standard library. No web framework, no ORM, no CSS framework, no client
bundler.

**Why.** Package registries (npm, PyPI) are blocked by the egress policy of the
environment this was built in, so Next.js, React, Tailwind and Prisma were not
installable. Rather than ship something half-wired that cannot run, the app was
built on what is guaranteed present: `wsgiref`, `sqlite3`, `http.cookies`,
`hashlib`, `unittest`.

**What this buys.** `python3 -m fitness_platform serve` works on any machine
with Python 3.11 and nothing else. There is no build step, no lockfile drift and
no supply chain.

**What it costs, and how that is contained.** Every piece a framework would have
provided is present as a small, replaceable module rather than absent:

| Framework concern | Where it lives |
| --- | --- |
| Routing | `core/router.py` — typed path segments, method matching |
| Request/response | `core/request.py`, `core/response.py` |
| Middleware | `core/middleware.py` — session, CSRF, rate limit, headers |
| Templating | `web/ui/` — components as functions, escaping at every interpolation |
| ORM | `db/repositories/` — one module per aggregate, SQL kept in one layer |
| Migrations | `db/schema.sql` applied idempotently on connect |

Because the app is a plain WSGI callable, moving to gunicorn or uWSGI in
production is a deployment detail, not a rewrite.

## 2. The women/men split is a data rule, not a UI rule

This is the requirement the product cannot get wrong, so it is enforced in one
place and tested on its own.

* `domain/gender.py` holds the only definition of who may see what.
  `GenderPath` is what a *user* is on (female or male, never "all");
  `ContentScope` is what a *content row* is tagged with (female, male or all).
* `services/authorization.py` is the single chokepoint. `require_path` compares
  the URL segment against the path stored in the **session** — never against a
  form field, a cookie or a query parameter.
* Repository reads take a `GenderPath` and build the `WHERE` clause from
  `scope_sql`. A member asking for the other path's video id gets `None` from
  the repository, which the route turns into a 404 — not a 200 with the wrong
  content, and not a redirect that hints the row exists.
* `rules_engine.assert_scope` runs the check again on the way out of
  personalisation. It is redundant by design: a personalisation bug that leaks
  the other path's content is the one bug this product cannot ship.
* The AI coach never receives a database handle. Its context blocks are built
  from repositories called with the member's own path, so there is no filter for
  it to forget.

`tests/test_gender_isolation.py` is the executable version of this section. If
it fails, the product is broken regardless of what else passes.

## 3. Account creation happens before the questionnaire

The brief sketches: gender → questionnaire → preview → subscription → payment →
account. The account is created one step earlier, right after the path is
chosen.

**Why.** The brief also requires that a member who starts the questionnaire and
does not pay resumes exactly where they stopped. Progress that must survive a
device change has to live against a user row on the server; keeping it in a
cookie would lose it on the first phone-to-laptop switch and would put user data
somewhere the client can edit.

**What is unchanged.** Payment still gates everything. An account without an
active subscription can reach the questionnaire, the preview, the pricing page
and its own settings — and nothing else. `test_onboarding.py` and
`test_subscriptions.py` both assert this.

## 4. Personalisation: rules first, AI second

```
questionnaire → profile → rules engine (hard filters + ranking)
                              ↓
                     approved content only
                              ↓
                    AI layer (chooses/orders)  →  personalised program & menu
```

`domain/rules_engine.py` is a pure function of `(profile, candidate rows)`. It
excludes rather than ranks where exclusion is the right answer: an allergy, an
unapproved recipe, a workout two levels above the member, equipment they do not
own. The AI layer runs after it and may only pick from what survives.

The assistant is additionally bounded by `services/ai/safety.py`, which answers
medical-sounding questions with a fixed referral instead of passing them to a
model, and refuses prompt-injection attempts. It has no tools and no write
access: it cannot cancel a subscription, delete content or change a permission.

## 5. Payments: only a signed webhook grants access

`services/payments/` defines `PaymentProvider` (checkout, webhook verification,
cancel) and a mock implementation. Access is granted in exactly one place —
`billing_service.handle_webhook` — after the provider verifies the signature.
Nothing the browser posts can activate a subscription.

The mock provider follows the same path: confirming the development checkout
builds an HMAC-signed event and posts it through that same handler, so the code
that runs in development is the code that runs in production. The development
checkout screen collects no payment details at all, because a realistic-looking
fake card form is precisely the kind of fake this codebase avoids.

Webhook ids are recorded, so a replayed delivery is a no-op rather than a second
charge (`test_subscriptions.py::test_replayed_event_is_a_no_op`).

## 6. Rendering: server-side components, progressive enhancement

Pages are assembled from functions in `web/ui/components.py` and rendered on the
server. Every interpolation goes through `esc()`; there is no "safe" escape
hatch that a future edit can misuse.

JavaScript is additive: the drawer, toasts, modals, optimistic checkboxes and
the AI chat. Everything else — including every form and every filter — works
with scripting disabled. That is what allows the Content-Security-Policy to be
strict (`script-src 'self'`, no `unsafe-inline`).

Charts are server-rendered SVG (`web/ui/charts.py`) reading their colours from
CSS custom properties, so they re-theme with the rest of the page and cost no
client-side library.

## 7. Theming: one layout, three palettes

`static/css/tokens.css` defines the scale (space, radius, type, shadow) once and
then three palettes on top of it: `.theme-women`, `.theme-men`, `.theme-admin`.
No screen names a colour directly. The member area for both paths is *one*
implementation — the same routes, the same components — differing only by the
theme class and by the content the session's path allows. Adding a third path
later is a palette plus a `GenderPath` member, not a second application.

RTL is the default, not a mode: layout uses logical properties
(`inset-inline-start`, `margin-inline`), and only the icons that carry direction
are mirrored (`icons.FLIPPED`). A play triangle is deliberately not mirrored —
it points along playback, which stays left-to-right.

## 8. Database

SQLite through `sqlite3`, one connection per thread, foreign keys switched on
explicitly (SQLite leaves them off, which silently turns every `REFERENCES`
clause into a comment). List-shaped columns are JSON text, encoded and decoded
in `db/json_fields.py` alone — the one file a Postgres port (where they become
real arrays) would need to touch, alongside the DDL spellings in `schema.sql`.

Repositories return domain objects, never `sqlite3.Row`, so nothing above the db
package knows a column name or can accidentally render one.

## 9. What is deliberately not built

* **Community feed.** The screen exists with an honest empty state rather than
  fake posts.
* **Real video hosting.** `StorageProvider` is defined with a local
  implementation; the player uses a real `<video>` when a URL exists and shows a
  clearly-labelled placeholder when it does not.
* **Roles beyond user/admin.** `CONTENT_MANAGER` and `NUTRITION_SPECIALIST`
  parse and store today so the column needs no migration, but they are granted
  no extra permissions yet.
* **Email.** No verification or password-reset mail, since no provider is wired.

Each of these is a seam, not a stub that pretends to work.

## 10. Testing

`python -m unittest discover -s tests -t .` — 196 tests, no external runner.
Tests drive the real WSGI pipeline through a small client (`tests/helpers.py`),
so routing, middleware, CSRF and the guards all execute. Each test gets a fresh
in-memory database.

The suite is organised by risk, not by file layout:

| File | What it protects |
| --- | --- |
| `test_gender_isolation.py` | the women/men boundary, at every layer |
| `test_auth.py` | hashing, sessions, CSRF, rate limits, headers |
| `test_onboarding.py` | validation, persistence, resumption |
| `test_subscriptions.py` | webhook signatures, replays, lifecycle |
| `test_rules_engine.py` | allergy/equipment/level exclusions, ranking |
| `test_ai_coach.py` | safety guards, provider failure, quota |
| `test_admin.py` | role boundary, CRUD, audit trail |
| `test_member_app.py` | member screens, ownership, empty states |
| `test_ui.py` | escaping, components, charts, analytics |
