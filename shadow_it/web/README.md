# Shadow IT dashboard

Next.js (App Router) frontend for the discovery API. Deliberately small: it
reads the inventory and starts scans, and it does both from the server.

## The one design rule

**The API key never reaches the browser.** It is an operator key that can read
every tenant, so it lives only in the Next.js server process:

- Pages are server components; they call the API through `lib/api.ts` at render
  time and ship HTML.
- The only mutation, "run scan", posts to this app's own route handler
  (`app/api/scan/route.ts`), which validates the tenant id and forwards the call
  with the key attached server-side.
- Nothing is exposed as `NEXT_PUBLIC_*`.

A side effect worth knowing: because no browser request ever hits the API
directly, `CORS_ORIGINS` on the backend can stay empty.

## Pages

| Route | Shows |
|---|---|
| `/` | tenant picker |
| `/tenants/{id}` | counts by band, scan state, filters, the app table |
| `/tenants/{id}/apps/{appId}` | score reasons, capabilities, scopes, who granted it |

Filters are a plain `<form method="get">` — the server component re-renders from
the URL, so the state is shareable and needs no client JavaScript.

## Environment

| Variable | Purpose |
|---|---|
| `API_URL` | Base URL of the discovery API (`http://api:8000` in compose) |
| `API_KEY` | Operator key; must match the API's `API_KEY` |

## Local development

Against a backend already running on port 8000:

```bash
npm install
API_URL=http://localhost:8000 API_KEY=<your key> npm run dev
```

Or run the whole stack from the parent directory with `docker compose up`.
