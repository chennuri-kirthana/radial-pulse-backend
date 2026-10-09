"""The ORM models (app/models) match db/schema-v15.sql exactly (prompts Step D).

Compared with the REAL database built by the baseline migration: same tables, same columns,
same types, same nullability, same "has a default", same primary keys and foreign keys.
Any difference fails, so a model can never drift from the database.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.dialects import postgresql

import app.models  # noqa: F401  (registers every model)
from app.db.base import Base
from tests.schema_v15.helpers import fresh_database

pytestmark = pytest.mark.integration

PG = postgresql.dialect()


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with fresh_database("t07", seed=False) as d:
        eng = create_engine(d.url)
        yield eng
        eng.dispose()


def _type(t: Any) -> str:
    return str(t.compile(dialect=PG)).replace(" ", "")


def db_tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def test_same_22_tables(engine: Engine) -> None:
    assert set(Base.metadata.tables) == db_tables(engine)
    assert len(Base.metadata.tables) == 22


@pytest.mark.parametrize("table", sorted(Base.metadata.tables))
def test_columns_match(engine: Engine, table: str) -> None:
    model = Base.metadata.tables[table]
    db_cols = {c["name"]: c for c in inspect(engine).get_columns(table)}
    assert set(model.columns.keys()) == set(db_cols), "column names differ"
    problems = []
    for col in model.columns:
        real = db_cols[col.name]
        if _type(col.type) != _type(real["type"]):
            problems.append(f"{col.name}: type {_type(col.type)} != {_type(real['type'])}")
        if col.nullable != real["nullable"]:
            problems.append(f"{col.name}: nullable {col.nullable} != {real['nullable']}")
        has_default = col.server_default is not None
        if has_default != (real["default"] is not None):
            problems.append(f"{col.name}: server default {has_default} != {real['default']!r}")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("table", sorted(Base.metadata.tables))
def test_keys_match(engine: Engine, table: str) -> None:
    model = Base.metadata.tables[table]
    insp = inspect(engine)
    assert {c.name for c in model.primary_key.columns} == set(
        insp.get_pk_constraint(table)["constrained_columns"]
    )

    def model_fks() -> set[tuple[tuple[str, ...], str, tuple[str, ...], str | None]]:
        return {
            (
                tuple(fk.column_keys),
                fk.referred_table.name,
                tuple(e.column.name for e in fk.elements),
                (fk.ondelete or "NO ACTION").upper(),
            )
            for fk in model.foreign_key_constraints
        }

    def real_fks() -> set[tuple[tuple[str, ...], str, tuple[str, ...], str | None]]:
        return {
            (
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
                (fk["options"].get("ondelete") or "NO ACTION").upper(),
            )
            for fk in insp.get_foreign_keys(table)
        }

    assert model_fks() == real_fks()
