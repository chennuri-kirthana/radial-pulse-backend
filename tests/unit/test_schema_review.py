"""Schema review rules (migration 0012), checked on the models so a new table cannot break them."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import Index, PrimaryKeyConstraint, Table, UniqueConstraint

import app.models  # noqa: F401  (fills Base.metadata)
from app.core.enums import WorkItemStatus
from app.db.base import Base
from app.models import WorkItem
from app.schemas.clinics import ClinicCreate

#: Users are never hard-deleted (they are deactivated), so "who did it" links to users do not need
#: an index for deletes. Everything else does.
NO_INDEX_NEEDED_FOR = {"users"}


def _is_partial(ix: Index) -> bool:
    return ix.dialect_options["postgresql"].get("where") is not None


def _column_lists(table: Table, *, include_partial: bool) -> list[list[str]]:
    """Column lists of every index / unique key / primary key of the table."""
    lists = [[c.name for c in ix.columns] for ix in table.indexes if include_partial or not _is_partial(ix)]
    lists += [
        [c.name for c in con.columns]
        for con in table.constraints
        if isinstance(con, (UniqueConstraint, PrimaryKeyConstraint))
    ]
    return [cols for cols in lists if cols]


def test_every_link_has_an_index_that_starts_with_it() -> None:
    """Without it, deleting a parent (or finding a parent's children) reads the whole child table."""
    missing = []
    for table in Base.metadata.sorted_tables:
        firsts = {cols[0] for cols in _column_lists(table, include_partial=True)}
        for fk in table.foreign_key_constraints:
            if fk.referred_table.name in NO_INDEX_NEEDED_FOR:
                continue
            first = next(iter(fk.columns)).name
            if first not in firsts:
                missing.append(f"{table.name}.{first}")
    assert missing == [], f"add an index for {missing}"


def test_no_single_column_index_duplicates_a_bigger_one() -> None:
    """An index on (a) is useless when an index or unique key on (a, …) exists: it only slows writes."""
    duplicates = []
    for table in Base.metadata.sorted_tables:
        covering = _column_lists(table, include_partial=False)
        for ix in table.indexes:
            cols = [c.name for c in ix.columns]
            if len(cols) != 1 or ix.unique or _is_partial(ix):
                continue
            if any(len(other) > 1 and other[0] == cols[0] for other in covering):
                duplicates.append(ix.name)
    assert duplicates == []


def test_one_running_assessment_per_clinic_is_a_database_rule() -> None:
    index = next(
        ix
        for ix in Base.metadata.tables["assessments"].indexes
        if ix.name == "uq_assessments_one_in_progress"
    )
    assert index.unique
    assert [c.name for c in index.columns] == ["clinic_id"]


def test_work_item_completed_at_follows_the_status() -> None:
    item = WorkItem(kind="k", title="t", status=WorkItemStatus.DONE)
    assert item.completed_at is not None
    item.status = WorkItemStatus.IN_PROGRESS
    assert item.completed_at is None


def test_country_is_stored_as_two_upper_case_letters() -> None:
    assert ClinicCreate(name="Smile", country=" in ").country == "IN"
    with pytest.raises(ValidationError, match="two-letter country code"):
        ClinicCreate(name="Smile", country="I1")
