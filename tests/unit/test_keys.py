"""Every table has a primary key; the engine contract matches the findings' natural key."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import app.models  # noqa: F401  (fills Base.metadata)
from app.assessments.engines import ComponentResult, FindingResult
from app.core.enums import ComponentStatus, FindingPriority
from app.db.base import Base


def test_every_table_has_a_primary_key() -> None:
    missing = [t.name for t in Base.metadata.sorted_tables if not t.primary_key.columns]
    assert missing == []


def test_same_clinic_links_are_composite_foreign_keys() -> None:
    """A child that stores clinic_id and points at a clinic-scoped parent links on BOTH columns."""
    tables = Base.metadata.tables
    expected = {
        ("assessment_components", ("assessment_id", "clinic_id")),
        ("assessment_findings", ("assessment_id", "clinic_id")),
        ("assessment_findings", ("component_id", "assessment_id")),
        ("report_artifacts", ("assessment_id", "clinic_id")),
        ("report_artifacts", ("asset_id", "clinic_id")),
        ("chat_messages", ("attachment_asset_id", "clinic_id")),
        ("clinics", ("cover_asset_id", "id")),
        ("assets", ("previous_version_id", "clinic_id")),
        ("work_items", ("approval_id", "clinic_id")),
    }
    found = {
        (name, tuple(c.name for c in fk.columns))
        for name, table in tables.items()
        for fk in table.foreign_key_constraints
        if len(fk.columns) > 1
    }
    assert expected <= found


def test_an_engine_may_not_report_the_same_problem_twice_in_one_section() -> None:
    finding = FindingResult(code="website.slow", title="Slow", priority=FindingPriority.LOW)
    with pytest.raises(ValidationError, match="only once per component"):
        ComponentResult(status=ComponentStatus.COMPLETED, score=50, findings=[finding, finding])
