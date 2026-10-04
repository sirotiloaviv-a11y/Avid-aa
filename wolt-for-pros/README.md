# Wolt for Pros

On-demand electricians, plumbers and handymen, with the speed and transparency
of a food-delivery app. The client books in a minute and watches the pro drive
over on a live map. The pro pays the platform fee from a prepaid wallet, and the
job only closes when the client hands over a 4-digit completion code.

```
wolt-for-pros/
├── backend/    Express + Prisma + Socket.io + Stripe (Node 18.18+)
└── frontend/   Next.js 14 App Router + Tailwind + Leaflet
```

## Instant preview: demo mode (no backend, no database)

```bash
cd frontend
npm install
npm run dev     # http://localhost:3000
```

If the API isn't reachable, the frontend switches to **demo mode**. It runs
against an in-browser mock of the API and Socket.io server
(`frontend/lib/demo/mockServer.js`) that applies the same rules as the backend:
fee holds, settlement, fraud flags, admin rulings and the wallet ledger. Every
page and workflow works unchanged. State is kept in `localStorage`.

A floating toolbar at the bottom switches between the **Client view**, the
**Tradesperson dashboard** and the **Admin panel**, and **resets the demo
data**. Opening `/client`, `/pro` or `/admin` directly signs you in as that
role's demo account.

Seeded scenario to try:

1. **Tradesperson dashboard.** Yossi Cohen (electrician, active) has ₪350
   available and ₪50 locked, and is assigned "Power Outlet Replacement"
   (₪400 estimate, ₪60 fee). Press **Top Up ₪100** to watch the balance count
   up. Press **Simulate driver movement** to drive him to the client.
2. **Client view.** Dana sees the same job live: the map, the ETA countdown,
   and completion code **4829**. The drive keeps running when you switch views,
   and the client view has its own **Simulate Driver Movement** button.
3. **Back on the dashboard.** Press **Finish job** and enter `4829` with the
   ₪400 price. The job closes, the ₪60 fee is settled and the ledger updates.
   Enter a price under ₪200 instead to trigger the anti-fraud flag.
4. **Admin panel.** A dispute is pre-loaded: "Unusual low price ₪150 vs ₪400
   estimate". **Approve** charges the fee on ₪150. **Reject** charges it on the
   ₪400 estimate. **Void** releases the fee.

Force a mode with `NEXT_PUBLIC_DEMO_MODE=true|false`, or add `?demo=1` to the
URL to stay in demo mode for that browser tab even while a backend is running.

Note on the seed: the ₪50 locked balance is less than the job's ₪60 fee, as
specified. The mock releases what is actually locked and takes the remaining
₪10 from the available balance. Completing the job at ₪400 leaves ₪340
available and ₪0 locked, and the ledger still balances.

## Quick start (local, SQLite, no Stripe account needed)

```bash
# 1. API on :4000
cd backend
cp .env.example .env
npm install
npm run db:push        # create the SQLite schema
npm run db:seed        # demo users and jobs around Tel Aviv
npm run dev

# 2. Web app on :3000 (second terminal)
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open http://localhost:3000 and use the demo buttons on the login screen:

| Phone        | Who                | Why it's interesting                                      |
|--------------|--------------------|-----------------------------------------------------------|
| `0501111111` | Dana, client       | Books jobs and tracks them live                           |
| `0502222222` | Yossi, electrician | Already has 1 flag: one more gets him auto-suspended      |
| `0503333333` | Moshe, plumber     | ₪30 balance: Accept is disabled until he tops up          |
| `0504444444` | Avi, handyman      | Plenty of balance                                         |
| `0500000000` | Noa, admin         | `/admin/flagged-jobs` dispute center                      |

**Two-window demo:** log in as Dana in one browser and Yossi in a private window.
Dana requests an electrician. The job appears on Yossi's radar instantly. Yossi
accepts and presses **Simulate drive**, and Dana's map shows him approaching
with a ticking ETA. Yossi taps **Finish job** and enters Dana's code and a final
price. Enter a price under 50% of the estimate to see the anti-fraud engine flag
the job and suspend him.

With `STRIPE_SECRET_KEY` empty the backend runs in **mock mode**: the top-up
modal credits the wallet directly, so the whole flow works offline.

## How the money works

All amounts are `Decimal` in the database and integer agorot in code, so fee
math never touches floating point. `Wallet.balance` is the **available** balance
and `Wallet.lockedBalance` holds fees for jobs in flight.

| Step | Wallet effect | Ledger rows (`WalletTransaction.amount`) |
|------|---------------|------------------------------------------|
| Top-up (Stripe webhook) | available + X | `deposit +X` |
| Accept job | requires available ≥ 15% of the estimate; moves it to locked | `fee_hold −fee` |
| Verify & complete (code OK, price normal) | releases the hold; charges 15% of the **final** price | `fee_deduction −finalFee`, plus `refund +diff` if the hold was larger |
| Verify & complete (price < 50% of the estimate) | hold **stays locked**; job → `flagged` | none until an admin resolves it |
| Cancel (client) / release (pro) | hold back to available | `refund +fee` |
| Admin resolves a flag | approve: fee on final price · uphold: fee on estimate · void: release hold | as above |
| Admin adjustment | ± available | `adjustment ±X` |

If the final fee is larger than the hold, the extra comes out of the available
balance, which can go negative. A negative balance blocks new jobs until the pro
tops up.

Concurrency: holds, releases and job status changes are conditional
`updateMany` calls inside one transaction (`WHERE balance >= fee`,
`WHERE status = 'requested'`). Two pros racing for the same job cannot both win,
and the loser's hold rolls back.

## Anti-fraud rules

- `final_price < 50% × estimated_price` → job `flagged`, `fraud_score + 1`, fee
  kept locked, admins notified live over the socket.
- ≥ 2 countable flags in 30 days → profile `suspended`. A flag stops counting
  once an admin **approves** it (rules the low price legitimate).
- The completion code is never sent to the tradesperson's API or socket
  payloads. After 5 wrong guesses the job locks (`423 CODE_LOCKED`).
- Suspended pros cannot go online or accept jobs. Only an admin can unblock them.

## API

All routes are under `/api` and take a `Authorization: Bearer <jwt>` header
except auth, catalog and webhooks. Errors look like
`{ "error": { "message", "code", "details" } }`.

| Method | Path | Role | Purpose |
|--------|------|------|---------|
| POST | `/auth/register` | public | Client or tradesperson sign-up |
| POST | `/auth/login` | public | Phone login (dev; see Production) |
| GET | `/auth/me` | any | Current user and profile |
| GET | `/catalog` | public | Services, price ranges, fee rate, top-up presets |
| GET | `/wallet/balance` | tradesperson | Available, locked, last 25 transactions |
| POST | `/wallet/deposit` | tradesperson | Direct credit, **mock / test mode only** |
| POST | `/wallet/checkout-session` | tradesperson | Stripe Checkout for a top-up (`{ amount }`) |
| GET | `/wallet/checkout-session/:id` | tradesperson | Confirm a session after the redirect (idempotent) |
| POST | `/webhooks/stripe` | Stripe | `checkout.session.completed` credits the wallet |
| GET | `/pros/me` | tradesperson | Profile, wallet, active job |
| POST | `/pros/me/availability` | tradesperson | Go online / offline |
| POST | `/jobs/create` | client | New request (`serviceType, description, latitude, longitude, address?`) |
| GET | `/jobs/mine` | any | My jobs |
| GET | `/jobs/nearby` | tradesperson | Radar: open jobs of my trade within `radiusKm`, with fee, payout and `canAfford` |
| GET | `/jobs/:id` | participant / admin | One job (code included for its client only) |
| POST | `/jobs/:id/accept` | tradesperson | Balance check and fee hold |
| POST | `/jobs/:id/start` | tradesperson | Arrived: `assigned` → `in_progress` |
| POST | `/jobs/:id/verify-and-complete` | tradesperson | `{ completionCode, finalPrice }` |
| POST | `/jobs/:id/cancel` | participant / admin | Release the hold (a pro releasing puts the job back on the radar) |
| GET | `/admin/flagged-jobs?state=open\|resolved\|all` | admin | Disputes |
| POST | `/admin/flagged-jobs` | admin | `{ jobId, action: approve\|charge_estimate\|void, note? }` |
| GET | `/admin/tradespeople` | admin | Status, flags in window, balances |
| POST | `/admin/tradespeople/:userId/status` | admin | `{ status: active\|inactive\|suspended }` (unblock) |
| POST | `/admin/wallets/:userId/adjust` | admin | `{ amount: ±number, note? }` |

### Socket.io

Connect with `io(API_URL, { auth: { token } })`. Every user joins `user:<id>`,
tradespeople join `pros:<serviceType>`, and admins join `admins`.

| Direction | Event | Payload |
|-----------|-------|---------|
| client → server | `job:subscribe` (ack) | `{ jobId }` → `{ ok, location }` with the last known pro position |
| pro → server | `location:update` (ack) | `{ lat, lng, heading? }`, throttled to 1/s and persisted every 15 s |
| server → job room | `pro:location` | `{ jobId, lat, lng, distanceKm, etaMinutes, at }` |
| server → participants | `job:updated` | the job (never includes the code) |
| server → pros of the trade | `job:new`, `job:taken` | radar updates |
| server → pro | `wallet:updated`, `profile:updated` | balance and suspension changes |
| server → admins | `flagged:new` | a job just got flagged |

## Stripe

1. Put your test keys in `backend/.env` (`STRIPE_SECRET_KEY=sk_test_...`).
2. Forward webhooks locally: `stripe listen --forward-to localhost:4000/api/webhooks/stripe`,
   then copy the printed `whsec_...` into `STRIPE_WEBHOOK_SECRET`.
3. Top up from the pro dashboard and pay with card `4242 4242 4242 4242`.

The wallet is credited from Stripe's `amount_total`, never from a client-sent
amount. Crediting is keyed on the Checkout Session id (a unique column), so a
webhook that is delivered twice, or a webhook plus the post-redirect
confirmation, credits once. Currency is ILS.

## PostgreSQL

```bash
cd backend
npm run db:use-postgres          # switches the Prisma provider
# DATABASE_URL="postgresql://user:pass@localhost:5432/wolt_for_pros"
npm run db:push && npm run db:seed
```

Status and type columns are strings validated in code
(`src/domain/constants.js`), so the same schema runs on both databases.

## Tests

```bash
cd backend && npm test
```

These cover the money, fee settlement, fraud thresholds and geo helpers as pure
functions. They need no database.

## Before production

This is a complete MVP, not a hardened deployment. Known gaps:

- **Login is phone-only, with no verification.** Add an SMS one-time code (e.g.
  Twilio Verify) in front of `/auth/login` and `/auth/register`.
- **No rate limiting.** Add it on auth, job creation and `verify-and-complete`.
- **License numbers are not verified** against the registry of licensed
  electricians and plumbers.
- **Migrations.** Use `prisma migrate` instead of `db push`.
- **One API instance only.** The live location cache is in memory. Use the
  Socket.io Redis adapter and a shared store to run more than one instance.
- **Exact job location** is visible on the radar before acceptance. Consider
  blurring it until a pro accepts.
- **Straight-line ETA** at 30 km/h. Swap in a routing API for road ETAs.
