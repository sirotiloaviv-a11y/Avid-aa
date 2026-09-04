# `api/` — product HTTP API

A small TypeScript HTTP API over the product catalogue. Currently it serves one
route: a product's live stock position.

Dependency-free, like the rest of this repository — the HTTP server, the SQLite
driver, the test runner and the TypeScript support are all Node builtins. There
is no build step and no `node_modules`.

Requires **Node 22.18 or newer**, which runs `.ts` files directly by stripping
the types.

## Running

```bash
cd api
npm start                       # http://127.0.0.1:3000
```

| Variable        | Default              | Meaning                                  |
| --------------- | -------------------- | ---------------------------------------- |
| `PORT`          | `3000`               | Port to bind                             |
| `HOST`          | `127.0.0.1`          | Interface to bind                        |
| `DATABASE_PATH` | `./data/products.db` | SQLite file; `:memory:` for a scratch db |

## Checks

```bash
npm test         # unit + route tests
npm run typecheck
```

## `GET /api/products/:id/availability`

`:id` is a positive integer with no leading zeros.

**200** — the product exists:

```json
{ "productId": "123", "available": true, "quantity": 17 }
```

`available` is `quantity > 0`. A product that exists but has never been stocked
has no `product_inventory` row; that reads as `quantity: 0`, not as a 404.

**400** — the ID is not a positive integer:

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "productId must be a positive integer without leading zeros",
    "field": "productId"
  }
}
```

**404** — no product carries that ID:

```json
{ "error": { "code": "NOT_FOUND", "message": "Product '999' was not found" } }
```

## Layout

```
src/
  domain/        Types and errors. Knows nothing about HTTP or SQL.
  validation/    Turns untrusted input into domain values, or throws.
  db/            Schema and connection factory.
  repositories/  SQL. The only layer that writes a query.
  services/      Business rules. Composes validation and repositories.
  controllers/   Domain result -> HTTP response.
  http/          Router, error mapping, server, wiring.
  types/         Ambient declarations for Node builtins (see the file's note).
tests/
```

Errors travel as exceptions and become status codes in exactly one place,
`http/error-mapper.ts`, so no layer below it has to know it is behind an API.

`createApp()` returns a plain `(method, path) => response` function and the
`node:http` server is a thin shell around it, which is what lets the route
tests exercise real routing, real validation and a real database without
binding a port.

## Adding a route

1. Add the query to a repository.
2. Put the rule in a service; throw `ValidationError` or `NotFoundError`.
3. Add a controller method returning `json(status, body)`.
4. Register it on the router in `http/app.ts`.
5. Test the service against an in-memory database, and the route through
   `createApp()`.
