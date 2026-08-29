# Veyra Security Brain

Application scaffold. **No product functionality is implemented yet** — this
repository currently contains the development environment, build tooling and
database wiring that later phases build on.

## Stack

| Concern    | Choice                                     |
| ---------- | ------------------------------------------ |
| Framework  | Next.js (App Router)                       |
| Language   | TypeScript, `strict` mode                  |
| Styling    | Tailwind CSS v4 (CSS-first configuration)  |
| Database   | PostgreSQL 16                              |
| ORM        | Prisma                                     |
| Linting    | ESLint (flat config, `eslint-config-next`) |
| Formatting | Prettier                                   |

## Requirements

- Node.js **>= 20.9** (developed against v22)
- PostgreSQL 16, either via Docker or a local server
- npm (pnpm and yarn also work; the scripts are package-manager agnostic)

## Getting started

```bash
# 1. Install dependencies
npm install

# 2. Create your local environment file
cp .env.example .env
#    Then open .env and set POSTGRES_PASSWORD and the matching password in
#    DATABASE_URL. Never commit this file.

# 3. Start PostgreSQL
docker compose up -d
#    Or point DATABASE_URL at an existing PostgreSQL 16 server.

# 4. Generate the Prisma client and apply migrations
npm run db:migrate

# 5. Run the development server
npm run dev
```

The app is then served at http://localhost:3000, with a liveness probe at
http://localhost:3000/api/health.

## Scripts

| Script                 | Purpose                                            |
| ---------------------- | -------------------------------------------------- |
| `npm run dev`          | Development server with hot reload                 |
| `npm run build`        | Production build                                   |
| `npm run start`        | Serve a production build                           |
| `npm run lint`         | ESLint over the project                            |
| `npm run lint:fix`     | ESLint with autofix                                |
| `npm run typecheck`    | `tsc --noEmit`                                     |
| `npm run format`       | Prettier, writing changes                          |
| `npm run format:check` | Prettier, failing on unformatted files             |
| `npm run check`        | `format:check` + `lint` + `typecheck`              |
| `npm run db:generate`  | Regenerate the Prisma client                       |
| `npm run db:migrate`   | Create and apply a development migration           |
| `npm run db:deploy`    | Apply pending migrations (non-interactive, for CI) |
| `npm run db:studio`    | Prisma Studio                                      |

Run `npm run check` before opening a pull request.

## Project structure

```
veyra-security-brain/
├── prisma/
│   └── schema.prisma          # Datasource + generator. No models yet.
├── public/                    # Static assets served at the site root
├── src/
│   ├── app/                   # App Router entry points
│   │   ├── api/health/route.ts
│   │   ├── globals.css        # Tailwind import + design tokens
│   │   ├── layout.tsx
│   │   └── page.tsx
│   └── lib/
│       ├── env.ts             # Validated environment access
│       └── prisma.ts          # PrismaClient singleton
├── docker-compose.yml         # Local PostgreSQL only
├── eslint.config.mjs
├── next.config.ts             # Includes security response headers
├── postcss.config.mjs
└── tsconfig.json
```

## Environment variables

All configuration is read from the environment; nothing is hardcoded.
`src/lib/env.ts` is the single place `process.env` is read, and it throws at
startup if a required variable is missing rather than letting the app run
half-configured.

| Variable            | Required | Notes                                        |
| ------------------- | -------- | -------------------------------------------- |
| `DATABASE_URL`      | yes      | PostgreSQL connection string for Prisma      |
| `NODE_ENV`          | no       | `development` \| `test` \| `production`      |
| `APP_URL`           | no       | Defaults to `http://localhost:3000`          |
| `POSTGRES_USER`     | dev only | Consumed by `docker-compose.yml`             |
| `POSTGRES_PASSWORD` | dev only | Consumed by `docker-compose.yml`             |
| `POSTGRES_DB`       | dev only | Consumed by `docker-compose.yml`             |
| `POSTGRES_PORT`     | no       | Host port for the dev database, default 5432 |

See `.env.example` for the template. It contains placeholders only.

## Security notes

- **No secrets in the repository.** `.env` and every `.env.*` variant except
  `.env.example` are gitignored, alongside `*.pem`, `*.key`, `*.p12` and
  `*.pfx`. `.env.example` holds non-functional placeholders.
- **Secrets come from the environment.** In production, supply them from a
  secret manager rather than a `.env` file on disk.
- **Security headers** are set for every route in `next.config.ts`
  (`X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`,
  `Permissions-Policy`, and HSTS in production only). `poweredByHeader` is
  disabled.
- **The dev database is bound to `127.0.0.1`** in `docker-compose.yml`, so it
  is not reachable from the local network.
- **Type and lint errors fail the build.** `typescript.ignoreBuildErrors` and
  `eslint.ignoreDuringBuilds` are both explicitly `false`. Do not flip these to
  get a build through.

### Known gap

No Content-Security-Policy is set yet. A correct App Router policy needs
per-request nonces threaded through middleware, and a placeholder policy that
gets progressively loosened is worse than none. This is tracked for the phase
that introduces the first real pages, and is noted in `next.config.ts`.

## Not in scope yet

Deliberately not implemented at this stage:

- Any product functionality
- Google Workspace integration
- Customer dashboard
- CEO/admin dashboard
- Authentication and authorisation
- Prisma domain models
