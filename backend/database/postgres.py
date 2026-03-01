"""
PostgreSQL connection pool + query helper with SQLite fallback.

Uses asyncpg for PostgreSQL/Supabase connections in production.
Falls back to aiosqlite for local development and demo mode.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports -- neither asyncpg nor aiosqlite may be installed
# ---------------------------------------------------------------------------

asyncpg: Any = None
aiosqlite: Any = None

try:
    import asyncpg as _asyncpg
    asyncpg = _asyncpg
except ImportError:
    pass

try:
    import aiosqlite as _aiosqlite
    aiosqlite = _aiosqlite
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _record_to_dict(record) -> dict:
    """Convert an asyncpg Record to a plain dict."""
    return dict(record)


def _row_to_dict(row, description) -> dict:
    """Convert an aiosqlite row + cursor.description to a plain dict."""
    columns = [col[0] for col in description]
    return dict(zip(columns, row))


# ---------------------------------------------------------------------------
# DatabasePool
# ---------------------------------------------------------------------------

class DatabasePool:
    """
    Async database abstraction.

    * If the DATABASE_URL starts with ``postgresql`` and asyncpg is available,
      a connection pool is created via ``asyncpg.create_pool``.
    * Otherwise an in-memory (or file-backed) SQLite connection is used via
      ``aiosqlite`` so the application can still run without PostgreSQL.
    """

    def __init__(self) -> None:
        self._pool = None            # asyncpg pool
        self._sqlite_conn = None     # aiosqlite connection
        self._backend: str = "none"  # "postgres" | "sqlite" | "none"
        self._database_url: str = ""

    # -- properties ---------------------------------------------------------

    @property
    def backend(self) -> str:
        """Return the active backend name: 'postgres', 'sqlite', or 'none'."""
        return self._backend

    @property
    def is_connected(self) -> bool:
        return self._backend != "none"

    # -- connect / disconnect -----------------------------------------------

    async def connect(self, database_url: str) -> None:
        """
        Open a connection pool (PostgreSQL) or a single connection (SQLite).

        Parameters
        ----------
        database_url : str
            A ``postgresql://...`` or ``sqlite:///...`` connection string.
        """
        self._database_url = database_url

        if database_url.startswith("postgresql"):
            await self._connect_postgres(database_url)
        else:
            await self._connect_sqlite(database_url)

    async def _connect_postgres(self, database_url: str) -> None:
        if asyncpg is None:
            logger.warning(
                "asyncpg is not installed -- falling back to SQLite. "
                "Install asyncpg with: pip install asyncpg"
            )
            await self._connect_sqlite("sqlite:///./sentinel.db")
            return

        try:
            self._pool = await asyncpg.create_pool(
                database_url,
                min_size=2,
                max_size=10,
                command_timeout=30,
            )
            self._backend = "postgres"
            logger.info("Connected to PostgreSQL (pool size 2-10)")
        except Exception as exc:
            logger.error("PostgreSQL connection failed: %s -- falling back to SQLite", exc)
            await self._connect_sqlite("sqlite:///./sentinel.db")

    async def _connect_sqlite(self, database_url: str) -> None:
        if aiosqlite is None:
            logger.error(
                "Neither asyncpg nor aiosqlite is installed. "
                "Install at least one: pip install asyncpg  OR  pip install aiosqlite"
            )
            self._backend = "none"
            return

        # Parse path from "sqlite:///./sentinel.db" or use in-memory
        if database_url.startswith("sqlite:///"):
            db_path = database_url.replace("sqlite:///", "", 1)
        elif database_url.startswith("sqlite://"):
            db_path = database_url.replace("sqlite://", "", 1)
        else:
            db_path = ":memory:"

        try:
            self._sqlite_conn = await aiosqlite.connect(db_path)
            self._sqlite_conn.row_factory = None  # we handle conversion ourselves
            await self._sqlite_conn.execute("PRAGMA journal_mode=WAL")
            await self._sqlite_conn.execute("PRAGMA foreign_keys=ON")
            self._backend = "sqlite"
            logger.info("Connected to SQLite (%s)", db_path)
        except Exception as exc:
            logger.error("SQLite connection failed: %s", exc)
            self._backend = "none"

    async def disconnect(self) -> None:
        """Close all connections."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL pool closed")

        if self._sqlite_conn is not None:
            await self._sqlite_conn.close()
            self._sqlite_conn = None
            logger.info("SQLite connection closed")

        self._backend = "none"

    # -- query helpers -------------------------------------------------------

    async def execute(self, query: str, *args) -> str:
        """
        Execute a query (INSERT / UPDATE / DELETE / DDL).

        Returns the status string from PostgreSQL or 'OK' for SQLite.
        """
        if self._backend == "postgres":
            async with self._pool.acquire() as conn:
                return await conn.execute(query, *args)

        elif self._backend == "sqlite":
            sqlite_query = _pg_to_sqlite(query)
            async with self._sqlite_conn.execute(sqlite_query, args or ()) as cursor:
                await self._sqlite_conn.commit()
                return f"OK (rows affected: {cursor.rowcount})"

        raise RuntimeError("Database is not connected")

    async def fetch(self, query: str, *args) -> list[dict]:
        """
        Fetch multiple rows and return them as a list of dicts.
        """
        if self._backend == "postgres":
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
                return [_record_to_dict(r) for r in rows]

        elif self._backend == "sqlite":
            sqlite_query = _pg_to_sqlite(query)
            async with self._sqlite_conn.execute(sqlite_query, args or ()) as cursor:
                desc = cursor.description
                rows = await cursor.fetchall()
                if not desc:
                    return []
                return [_row_to_dict(r, desc) for r in rows]

        raise RuntimeError("Database is not connected")

    async def fetchone(self, query: str, *args) -> Optional[dict]:
        """
        Fetch a single row as a dict, or ``None`` if nothing matches.
        """
        if self._backend == "postgres":
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(query, *args)
                return _record_to_dict(row) if row else None

        elif self._backend == "sqlite":
            sqlite_query = _pg_to_sqlite(query)
            async with self._sqlite_conn.execute(sqlite_query, args or ()) as cursor:
                desc = cursor.description
                row = await cursor.fetchone()
                if row is None or desc is None:
                    return None
                return _row_to_dict(row, desc)

        raise RuntimeError("Database is not connected")

    async def fetchval(self, query: str, *args) -> Any:
        """
        Fetch a single scalar value (first column of first row).
        """
        if self._backend == "postgres":
            async with self._pool.acquire() as conn:
                return await conn.fetchval(query, *args)

        elif self._backend == "sqlite":
            sqlite_query = _pg_to_sqlite(query)
            async with self._sqlite_conn.execute(sqlite_query, args or ()) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

        raise RuntimeError("Database is not connected")

    # -- schema bootstrap ----------------------------------------------------

    async def bootstrap_schema(self) -> None:
        """
        Run the schema.sql file to create tables if they do not exist.

        For SQLite, PostgreSQL-specific syntax (UUID, JSONB, vector, etc.)
        is skipped or adapted automatically.
        """
        schema_path = Path(__file__).parent / "schema.sql"
        if not schema_path.exists():
            logger.warning("schema.sql not found at %s -- skipping bootstrap", schema_path)
            return

        sql = schema_path.read_text()

        if self._backend == "postgres":
            async with self._pool.acquire() as conn:
                await conn.execute(sql)
            logger.info("PostgreSQL schema bootstrapped")

        elif self._backend == "sqlite":
            # SQLite cannot run the full PG schema, so we run a simplified
            # version that strips PG-specific features.
            for statement in _split_sql_statements(sql):
                adapted = _pg_to_sqlite(statement)
                if adapted.strip():
                    try:
                        await self._sqlite_conn.execute(adapted)
                    except Exception as exc:
                        # Skip statements that SQLite cannot handle
                        # (e.g. CREATE INDEX ... USING hnsw)
                        logger.debug("Skipping unsupported SQLite statement: %s", exc)
            await self._sqlite_conn.commit()
            logger.info("SQLite schema bootstrapped (simplified)")

    # -- context manager -----------------------------------------------------

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.disconnect()


# ---------------------------------------------------------------------------
# SQLite compatibility helpers
# ---------------------------------------------------------------------------

def _pg_to_sqlite(query: str) -> str:
    """
    Best-effort translation of PostgreSQL query syntax into SQLite.

    This is intentionally simple -- it handles the most common differences
    so that basic CRUD operations work in demo mode.  The full schema uses
    ``bootstrap_schema`` which has additional handling.
    """
    import re

    q = query

    # $1, $2, ... positional params --> ?
    q = re.sub(r"\$\d+", "?", q)

    # Strip type casts like ::text, ::integer, ::jsonb
    q = re.sub(r"::\w+", "", q)

    # UUID default
    q = q.replace("gen_random_uuid()", "lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)),2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(hex(randomblob(2)),2) || '-' || hex(randomblob(6)))")

    # NOW() -> datetime('now')
    q = re.sub(r"\bNOW\(\)", "datetime('now')", q, flags=re.IGNORECASE)

    # TIMESTAMP WITH TIME ZONE -> TEXT
    q = re.sub(r"TIMESTAMP\s+WITH\s+TIME\s+ZONE", "TEXT", q, flags=re.IGNORECASE)

    # JSONB / JSON -> TEXT
    q = re.sub(r"\bJSONB\b", "TEXT", q, flags=re.IGNORECASE)
    q = re.sub(r"\bJSON\b", "TEXT", q, flags=re.IGNORECASE)

    # UUID type -> TEXT
    q = re.sub(r"\bUUID\b", "TEXT", q, flags=re.IGNORECASE)

    # DOUBLE PRECISION -> REAL
    q = re.sub(r"DOUBLE\s+PRECISION", "REAL", q, flags=re.IGNORECASE)

    # DECIMAL(...) -> REAL
    q = re.sub(r"DECIMAL\(\d+,\s*\d+\)", "REAL", q, flags=re.IGNORECASE)

    # VARCHAR(...) -> TEXT
    q = re.sub(r"VARCHAR\(\d+\)", "TEXT", q, flags=re.IGNORECASE)

    # vector(1536) -> TEXT  (pgvector)
    q = re.sub(r"\bvector\(\d+\)", "TEXT", q, flags=re.IGNORECASE)

    # BOOLEAN -> INTEGER
    q = re.sub(r"\bBOOLEAN\b", "INTEGER", q, flags=re.IGNORECASE)

    # TRUE / FALSE -> 1 / 0
    q = re.sub(r"\bTRUE\b", "1", q, flags=re.IGNORECASE)
    q = re.sub(r"\bFALSE\b", "0", q, flags=re.IGNORECASE)

    # Skip USING hnsw / gin / gist index methods -- SQLite only supports btree
    q = re.sub(r"\s+USING\s+(hnsw|gin|gist|brin)\b[^;]*", "", q, flags=re.IGNORECASE)

    # WITH (...) on CREATE INDEX -- strip operator class options
    q = re.sub(r"\s+WITH\s*\([^)]*\)", "", q, flags=re.IGNORECASE)

    # Skip CREATE EXTENSION
    if re.match(r"\s*CREATE\s+EXTENSION", q, re.IGNORECASE):
        return ""

    return q


def _split_sql_statements(sql: str) -> list[str]:
    """Split a SQL file on semicolons, respecting basic quoting."""
    statements: list[str] = []
    current: list[str] = []
    in_string = False
    escape_next = False

    for char in sql:
        if escape_next:
            current.append(char)
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            current.append(char)
            continue
        if char == "'":
            in_string = not in_string
            current.append(char)
            continue
        if char == ";" and not in_string:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            continue
        current.append(char)

    # Catch trailing statement without semicolon
    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)

    return statements


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

db = DatabasePool()


def get_db() -> DatabasePool:
    """Return the global database pool instance (for dependency injection)."""
    return db
