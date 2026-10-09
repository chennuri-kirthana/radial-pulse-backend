"""The baseline migration builds exactly db/schema-v15.sql, and can go down to empty and up again."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command

from tests.schema_v15.helpers import Db, alembic_config, fresh_database

pytestmark = pytest.mark.integration

COUNTS = """SELECT
  (SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'),
  (SELECT count(*) FROM pg_policies),
  (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity),
  (SELECT count(*) FROM pg_proc WHERE proname LIKE 'rp\\_%')"""


@pytest.fixture(scope="module")
def db() -> Iterator[Db]:
    with fresh_database("t00", seed=False) as d:
        yield d


def test_upgrade_builds_22_tables_65_policies_row_security_everywhere(db: Db) -> None:
    tables, policies, rls_on, functions = db.one(COUNTS)
    assert (tables, policies, rls_on) == (22, 65, 22)
    assert functions > 0
    assert db.one("SELECT version_num FROM alembic_version") == "v15_baseline"
    assert db.one("SELECT count(*) FROM pg_roles WHERE rolname IN ('radial_app', 'radial_service')") == 2


def test_downgrade_to_empty_then_upgrade_again(db: Db) -> None:
    cfg = alembic_config(db.url)
    command.downgrade(cfg, "base")
    assert db.one(COUNTS) == (0, 0, 0, 0)
    command.upgrade(cfg, "head")
    tables, policies, rls_on, _ = db.one(COUNTS)
    assert (tables, policies, rls_on) == (22, 65, 22)
