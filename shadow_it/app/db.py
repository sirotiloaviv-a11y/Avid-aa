"""Postgres access: one pool, and the schema applied on boot.

Deliberately not an ORM. The queries in ``services/repository.py`` are the only
SQL in the product, they are short, and a solo developer debugging a scan at
2am should be able to paste them straight into psql.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent / "sql" / "schema.sql"


class Database:
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 10):
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database.connect() has not been awaited")
        return self._pool

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            init=_register_json_codecs,
            # A scan holds a connection while it fans out; without a timeout a
            # stuck query would quietly starve the API.
            command_timeout=60,
        )
        log.info("Connected to Postgres (pool %d-%d)", self._min_size, self._max_size)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def apply_schema(self) -> None:
        """Run schema.sql. Idempotent, so it is safe on every boot."""
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(sql)
        log.info("Schema applied from %s", SCHEMA_PATH.name)

    async def healthcheck(self) -> bool:
        try:
            async with self.pool.acquire() as conn:
                return await conn.fetchval("SELECT 1") == 1
        except (asyncpg.PostgresError, OSError) as exc:
            log.warning("Database healthcheck failed: %s", exc)
            return False


async def _register_json_codecs(conn: asyncpg.Connection) -> None:
    """Make json/jsonb columns behave like Python objects on both sides.

    Without this asyncpg hands back the raw *string* for a jsonb column, so
    ``risk_reasons`` would be serialized to API clients as a JSON document
    nested inside a JSON string — valid, useless, and the kind of thing you
    only notice when a frontend tries to map over it.

    Registering the codec also means query parameters are plain Python objects:
    do not call ``json.dumps`` at the call site, and do not add ``::jsonb``
    casts, or the value gets encoded twice.
    """
    for type_name in ("json", "jsonb"):
        await conn.set_type_codec(
            type_name,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )
