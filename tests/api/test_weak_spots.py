"""Fixes for the schema review's weak spots: archiving (#3), metric numbers (#4), safe search (#6).

(#1 people-table locks, #5 shared doctors and #7 status-in-step are tested in
tests/integration/test_rls.py and tests/api/test_milestone1.py.)
"""

from __future__ import annotations

import gzip
import json
from datetime import timedelta
from pathlib import Path

import pytest

from app.core.enums import DataSource, SnapshotStatus
from app.db.base import utcnow
from app.integrations.archive import LocalArchiveStore
from app.models import AuditEvent, Clinic, MetricSnapshot
from app.services.archiving import archive_old_data
from tests.factories import make_clinic


# ------------------------------------------------------------------------ #3 archive
def _snapshot(clinic: Clinic, key: str, days_ago: int) -> MetricSnapshot:
    return MetricSnapshot(
        clinic_id=clinic.id, source=DataSource.MANUAL, metric_key=key, value={"value": days_ago},
        fetched_at=utcnow() - timedelta(days=days_ago), status=SnapshotStatus.OK,
    )  # fmt: skip


def _setup_old_and_new(db) -> Clinic:  # type: ignore[no-untyped-def]
    clinic = make_clinic(db, "Archive Clinic")
    db.add_all(
        [
            _snapshot(clinic, "instagram.old", 400),
            _snapshot(clinic, "instagram.new", 10),
            AuditEvent(action="old.event", resource_type="t", clinic_id=clinic.id,
                       occurred_at=utcnow() - timedelta(days=500), details={}),
            AuditEvent(action="new.event", resource_type="t", clinic_id=clinic.id,
                       occurred_at=utcnow() - timedelta(days=5), details={}),
        ]
    )  # fmt: skip
    db.commit()
    return clinic


def _archived(root: Path) -> list[dict]:  # type: ignore[type-arg]
    return [
        json.loads(line)
        for f in sorted(root.rglob("*.jsonl.gz"))
        for line in gzip.decompress(f.read_bytes()).splitlines()
    ]


def test_archive_moves_only_old_rows_to_the_archive(db, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _setup_old_and_new(db)
    results = archive_old_data(
        db, LocalArchiveStore(tmp_path), prefix="test", metrics_after_days=180, audit_after_days=365
    )
    assert [(r.table, r.rows) for r in results] == [("metric_snapshots", 1), ("audit_events", 1)]
    rows = _archived(tmp_path)
    assert {r.get("metric_key") or r.get("action") for r in rows} == {"instagram.old", "old.event"}
    # Folder per month of the row's own date (Athena-friendly).
    # as_posix(): same check on Windows, where str(path) uses backslashes.
    assert all("/year=" in p.as_posix() and "/month=" in p.as_posix() for p in tmp_path.rglob("*.jsonl.gz"))
    db.expire_all()
    assert [s.metric_key for s in db.query(MetricSnapshot).all()] == ["instagram.new"]
    assert [e.action for e in db.query(AuditEvent).all()] == ["new.event"]


def test_archive_dry_run_changes_nothing(db, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _setup_old_and_new(db)
    results = archive_old_data(
        db, LocalArchiveStore(tmp_path), prefix="test", metrics_after_days=180, audit_after_days=365,
        dry_run=True,
    )  # fmt: skip
    assert [r.rows for r in results] == [1, 1]
    assert list(tmp_path.rglob("*")) == []
    assert db.query(MetricSnapshot).count() == 2


def test_nothing_is_deleted_when_the_archive_write_fails(db) -> None:  # type: ignore[no-untyped-def]
    _setup_old_and_new(db)

    class BrokenStore:
        def put(self, key: str, body: bytes) -> None:
            raise OSError("S3 unavailable")

    with pytest.raises(OSError):
        archive_old_data(db, BrokenStore(), prefix="test", metrics_after_days=180, audit_after_days=365)
    db.rollback()
    assert db.query(MetricSnapshot).count() == 2
    assert db.query(AuditEvent).count() == 2


# ------------------------------------------------------------------- #4 metric numbers
def test_metric_numbers_are_stored_as_numbers(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    base = {"source": "instagram", "fetched_at": "2026-09-25T06:00:00Z", "status": "ok"}
    snaps = [
        {**base, "metric_key": "instagram.followers", "value": {"value": 5432}},
        {**base, "metric_key": "instagram.engagement_rate", "value": {"value": 4.8}},
        {**base, "metric_key": "instagram.verified", "value": {"value": True}},  # not a number
        {**base, "metric_key": "instagram.top_post", "value": {"url": "https://x"}},
    ]
    r = client.post(
        f"/api/v1/clinics/{world.clinic_a.id}/snapshots", headers=auth(world.dsm_a), json={"snapshots": snaps}
    )
    assert r.status_code == 201, r.text
    assert [s["value_number"] for s in r.json()] == [5432.0, 4.8, None, None]


# -------------------------------------------------------------------- #6 safe search
def test_search_treats_percent_and_underscore_as_plain_text(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    make_clinic(db, "100% Smile")
    make_clinic(db, "1000 Smiles")
    make_clinic(db, "Smile_Care")
    make_clinic(db, "SmileXCare")

    def names(q: str) -> set[str]:
        r = client.get("/api/v1/clinics", headers=auth(world.admin), params={"q": q})
        assert r.status_code == 200
        return {c["name"] for c in r.json()["items"]}

    assert names("100%") == {"100% Smile"}
    assert names("smile_care") == {"Smile_Care"}
