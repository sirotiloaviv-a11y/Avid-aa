"""FastAPI entry point.

    uvicorn app.main:app --reload          # development
    python -m app.main --check             # validate config and exit
    python -m app.main --scan <tenant_id>  # run one scan from the CLI

Everything expensive (pool, schema, scheduler) is built in the lifespan hook,
so importing this module stays cheap for tests and for the CLI paths.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import connect, inventory, tenants
from .api.deps import AppContext
from .config import Settings, settings
from .crypto import SecretBox
from .db import Database
from .services import Repository, ScanService, Scheduler

log = logging.getLogger("shadow_it")


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # These libraries log request URLs, which for us can contain tenant ids.
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def build_context(config: Settings) -> tuple[AppContext, Scheduler]:
    db = Database(config.dsn, config.db_pool_min, config.db_pool_max)
    await db.connect()
    if config.run_migrations_on_start:
        await db.apply_schema()

    secrets_box = SecretBox.from_keys(config.encryption_key, config.encryption_keys)
    repo = Repository(db.pool, secrets_box)
    scans = ScanService(repo, config)
    scheduler = Scheduler(scans, repo, config.scan_interval_hours)
    return AppContext(config, db, repo, scans, secrets_box), scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    config: Settings = app.state.settings
    problems = config.validate()
    if problems:
        for problem in problems:
            log.error("Config error: %s", problem)
        raise RuntimeError("Refusing to start with an invalid configuration")

    context, scheduler = await build_context(config)
    app.state.context = context
    scheduler.start()
    log.info("Shadow IT discovery API ready on %s", config.public_base_url)
    try:
        yield
    finally:
        await scheduler.stop()
        await context.db.close()


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or settings
    setup_logging(config.log_level)

    app = FastAPI(
        title="Shadow IT Discovery",
        version="0.1.0",
        summary="Discover and monitor unsanctioned third-party apps connected "
                "to Google Workspace and Microsoft 365.",
        lifespan=lifespan,
    )
    app.state.settings = config

    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.include_router(tenants.router)
    app.include_router(connect.router)
    app.include_router(inventory.router)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict:
        """Liveness + database reachability, for the container healthcheck."""
        context = getattr(app.state, "context", None)
        db_ok = await context.db.healthcheck() if context else False
        return {"ok": db_ok, "database": "up" if db_ok else "down"}

    return app


app = create_app()


# ------------------------------------------------------------------ cli ----
async def _cli_scan(tenant_id: str, config: Settings) -> int:
    context, _ = await build_context(config)
    try:
        result = await context.scans.run_scan(tenant_id)
        print(
            f"users={result.users_scanned} grants={result.grants_found} "
            f"apps={result.apps_found} new={result.new_apps}"
        )
        for error in result.errors[:10]:
            print(f"  ! {error}")
        return 1 if result.errors and not result.apps_found else 0
    finally:
        await context.db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Shadow IT discovery service")
    parser.add_argument("--check", action="store_true", help="validate config and exit")
    parser.add_argument("--migrate", action="store_true", help="apply the schema and exit")
    parser.add_argument("--scan", metavar="TENANT_ID", help="run one scan and exit")
    parser.add_argument("--serve", action="store_true", help="run the HTTP server")
    args = parser.parse_args(argv)

    config = settings
    setup_logging(config.log_level)

    problems = config.validate()
    if args.check:
        for problem in problems:
            print(f"ERROR: {problem}")
        print("Configuration OK" if not problems else "Configuration incomplete")
        return 1 if problems else 0
    if problems:
        for problem in problems:
            log.error("Config error: %s", problem)
        return 1

    if args.migrate:
        async def _migrate() -> None:
            db = Database(config.dsn)
            await db.connect()
            await db.apply_schema()
            await db.close()

        asyncio.run(_migrate())
        print("Schema applied.")
        return 0

    if args.scan:
        return asyncio.run(_cli_scan(args.scan, config))

    import uvicorn

    uvicorn.run(
        "app.main:app", host=config.host, port=config.port, log_config=None, access_log=False
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
