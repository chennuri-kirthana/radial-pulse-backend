"""Tests of the database itself (db/schema-v15.sql), ported from db/tests/*.sql.

Each test file gets its OWN fresh database, built by the real Alembic baseline migration,
like docs/03-backend-rules.md section 7 asks:
  01 + 02 on one fresh database · 03, 04 and 05 each on another fresh database + the seed.

The tests talk to PostgreSQL directly as the OWNER (like psql in the .sql files) and use
autocommit, so every statement is its own transaction, exactly as psql runs the files.
Access-rule tests switch to the app role with SET ROLE radial_app (test code only; the app
itself must use SET LOCAL / set_config(..., true)).

Needs TEST_DATABASE_URL (owner login, allowed to create databases). Run: make schema-test
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
SEED_FILE = ROOT / "db" / "seed-family-dental-v15.sql"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# Short ids from db/seed-family-dental-v15.sql
ANIL = "00000000-0000-0000-0000-00000000aa01"  # Platform Administrator
RAVI = "00000000-0000-0000-0000-00000000aa02"  # DSM of Shah Healthcare
MEHUL = "00000000-0000-0000-0000-00000000aa03"  # Clinic Administrator of Family Dental
POOJA = "00000000-0000-0000-0000-00000000aa04"  # practitioner login
PRIYA = "00000000-0000-0000-0000-00000000aa05"  # DSM of SmileCare (added by test 04)
KIRAN = "00000000-0000-0000-0000-00000000aa06"  # Clinic Administrator of SmileCare (test 04)
SITA = "00000000-0000-0000-0000-00000000aa07"  # Clinic Team Member of Family Dental (test 04)
CLINIC = "00000000-0000-0000-0000-00000000cc01"
PRACTITIONER = "00000000-0000-0000-0000-00000000dd01"


def _libpq_url(sqlalchemy_url: str, database: str | None = None) -> str:
    url = make_url(sqlalchemy_url).set(drivername="postgresql")
    if database:
        url = url.set(database=database)
    return url.render_as_string(hide_password=False)


def alembic_config(database_url: str) -> Config:
    """Alembic, pointed at one test database (SQLAlchemy URL, owner login)."""
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


def run_sql_file(conn: psycopg.Connection[Any], path: Path) -> None:
    """Run a .sql file written for psql: psql's own commands (lines starting with a backslash)
    are left out, the rest is sent in one go."""
    sql = "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("\\")
    )
    conn.execute(sql.encode())


@contextmanager
def fresh_database(name: str, *, seed: bool) -> Iterator[Db]:
    if not TEST_DATABASE_URL:
        pytest.skip("needs PostgreSQL: set TEST_DATABASE_URL")
    db_name = f"rp_v15_{name}_{uuid.uuid4().hex[:6]}"
    admin_url = _libpq_url(TEST_DATABASE_URL, "postgres")
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{db_name}"'.encode())
    try:
        sa_url = make_url(TEST_DATABASE_URL).set(database=db_name).render_as_string(hide_password=False)
        command.upgrade(alembic_config(sa_url), "head")  # the REAL baseline migration
        with psycopg.connect(_libpq_url(TEST_DATABASE_URL, db_name), autocommit=True) as conn:
            if seed:
                run_sql_file(conn, SEED_FILE)
            yield Db(conn, sa_url)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'.encode())


# ----------------------------------------------------------------------------------- helpers
class Db:
    """Small helpers so each "expect ERROR / OK" line of the .sql files is one assertion."""

    def __init__(self, conn: psycopg.Connection[Any], url: str) -> None:
        self.conn = conn
        self.url = url  # SQLAlchemy URL of this test database (owner login)

    def ok(self, sql: str, params: Any = None) -> int:
        """Runs without error; returns the number of rows changed / returned."""
        cur = self.conn.execute(sql.encode() if params is None else sql, params)
        return cur.rowcount

    def rows(self, sql: str, params: Any = None) -> list[tuple[Any, ...]]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: Any = None) -> Any:
        row = self.conn.execute(sql, params).fetchone()
        assert row is not None
        return row[0] if len(row) == 1 else row

    def error(self, sql: str, sqlstate: str, match: str | None = None) -> None:
        """Fails with this PostgreSQL error code (and message, if given)."""
        with pytest.raises(psycopg.Error) as caught:
            self.conn.execute(sql.encode())
        assert caught.value.sqlstate == sqlstate, f"{caught.value.sqlstate}: {caught.value}"
        if match:
            assert re.search(match, str(caught.value)), str(caught.value)

    def as_user(self, user_id: str | None) -> None:
        """Act as the app (row-level security on) for this user; None = nobody signed in."""
        self.conn.execute(b"SET ROLE radial_app")
        if user_id is None:
            self.conn.execute(b"RESET rp.user_id")
        else:
            self.conn.execute("SELECT set_config('rp.user_id', %s, false)", (user_id,))

    def as_owner(self) -> None:
        self.conn.execute(b"RESET ROLE")
        self.conn.execute(b"RESET rp.user_id")


# PostgreSQL error codes used by the tests
CHECK = "23514"  # check_violation (CHECK rules and the schema's triggers)
UNIQUE = "23505"  # unique_violation
FOREIGN_KEY = "23503"  # foreign_key_violation
NOT_NULL = "23502"  # not_null_violation
PRIVILEGE = "42501"  # insufficient_privilege (permissions, row-level security, guard triggers)
NO_COLUMN = "42703"  # undefined_column
