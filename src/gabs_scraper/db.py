"""Postgres connection helpers.

Prefers psycopg (v3); falls back to pg8000 (pure Python) so the pipeline works
even where no psycopg binary wheel is available for the interpreter.
Both drivers use ``%s`` placeholders, so callers write portable SQL.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import settings


def connect(dsn: str | None = None):
    dsn = dsn or settings.database_url
    try:
        import psycopg  # type: ignore

        return psycopg.connect(dsn)
    except ModuleNotFoundError:
        pass

    import pg8000.dbapi as pg  # type: ignore

    u = urlparse(dsn)
    return pg.connect(
        user=unquote(u.username or ""),
        password=unquote(u.password or ""),
        host=u.hostname or "localhost",
        port=u.port or 5432,
        database=(u.path or "/").lstrip("/") or "postgres",
    )


def _split_statements(sql: str) -> list[str]:
    # Schema uses no semicolons inside literals/bodies, so a naive split is safe.
    return [s.strip() for s in sql.split(";") if s.strip()]


def apply_schema(conn, schema_path: str | Path | None = None) -> None:
    path = Path(schema_path) if schema_path else settings.schema_path
    sql = path.read_text(encoding="utf-8")
    cur = conn.cursor()
    for stmt in _split_statements(sql):
        cur.execute(stmt)
    conn.commit()
