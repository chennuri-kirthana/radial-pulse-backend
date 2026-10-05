"""Move old rows out of the database into the S3 archive (weak spot #3).

Two tables grow forever: ``metric_snapshots`` (numbers over time) and ``audit_events`` (the log
of every action). Rows older than a cut-off are copied to S3 as gzipped JSON lines, then deleted
from the database — in that order, inside one transaction per batch:

    select a batch  →  write file(s) to S3  →  delete exactly those rows  →  commit

If the S3 write fails, the transaction rolls back and nothing is deleted. If the delete fails
after a successful write, the rows stay in the database and the next run copies them again
(archive readers must de-duplicate by ``id``; see docs/infrastructure/archiving.md).

S3 layout (Athena / Glue friendly, one folder per month of the row's own date):

    <env>/<table>/year=YYYY/month=MM/<run id>-<batch>.jsonl.gz

This runs as an OPERATOR task with the database owner login (like migrations): it is not
subject to row-level security, and it is the only login allowed to delete audit rows — and even
then only with ``app.archiving = on`` set in its transaction (migration 0009).
"""

from __future__ import annotations

import gzip
import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Column, Table, delete, func, select, text
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.integrations.archive import ArchiveStore
from app.models import AuditEvent, MetricSnapshot

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 5000


@dataclass(frozen=True)
class ArchiveTarget:
    table: Table
    time_column: Column[Any]
    #: audit_events is append-only; its trigger allows deletes only for the archive job.
    needs_archive_flag: bool = False


TARGETS = {
    "metric_snapshots": ArchiveTarget(MetricSnapshot.__table__, MetricSnapshot.__table__.c.fetched_at),  # type: ignore[arg-type]
    "audit_events": ArchiveTarget(
        AuditEvent.__table__,  # type: ignore[arg-type]
        AuditEvent.__table__.c.occurred_at,  # type: ignore[arg-type]
        needs_archive_flag=True,
    ),
}


@dataclass
class TableResult:
    table: str
    cutoff: datetime
    rows: int = 0
    files: list[str] = field(default_factory=list)


def _json_default(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"cannot archive a {type(value).__name__}")


def _encode(rows: list[dict[str, Any]]) -> bytes:
    lines = "".join(json.dumps(r, default=_json_default, sort_keys=True) + "\n" for r in rows)
    return gzip.compress(lines.encode("utf-8"))


def archive_table(
    session: Session,
    store: ArchiveStore,
    name: str,
    cutoff: datetime,
    *,
    prefix: str,
    run_id: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
) -> TableResult:
    """Archive rows of ``name`` older than ``cutoff``. Returns what was (or would be) moved."""
    target = TARGETS[name]
    result = TableResult(table=name, cutoff=cutoff)
    table, when = target.table, target.time_column
    older = when < cutoff

    if dry_run:
        result.rows = int(session.scalar(select(func.count()).select_from(table).where(older)) or 0)
        session.rollback()
        return result

    batch_no = 0
    while True:
        rows = [dict(r._mapping) for r in session.execute(
            select(table).where(older).order_by(when, table.c.id).limit(batch_size)
        )]  # fmt: skip
        if not rows:
            session.commit()
            break
        by_month: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            stamp = row[when.name]
            by_month[(stamp.year, stamp.month)].append(row)
        for (year, month), month_rows in sorted(by_month.items()):
            key = f"{prefix}/{name}/year={year:04d}/month={month:02d}/{run_id}-{batch_no:04d}.jsonl.gz"
            store.put(key, _encode(month_rows))  # raises → rollback → nothing deleted
            result.files.append(key)
        if target.needs_archive_flag and session.get_bind().dialect.name == "postgresql":
            session.execute(text("SELECT set_config('app.archiving', 'on', true)"))
        session.execute(delete(table).where(table.c.id.in_([r["id"] for r in rows])))
        session.commit()
        result.rows += len(rows)
        batch_no += 1
        logger.info("archived batch", extra={"table": name, "rows": len(rows), "batch": batch_no})
    return result


def archive_old_data(
    session: Session,
    store: ArchiveStore,
    *,
    prefix: str,
    metrics_after_days: int,
    audit_after_days: int,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
    now: datetime | None = None,
) -> list[TableResult]:
    """Archive both growing tables. ``session`` must use the database OWNER login."""
    now = now or utcnow()
    run_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    plan = [
        ("metric_snapshots", now - timedelta(days=metrics_after_days)),
        ("audit_events", now - timedelta(days=audit_after_days)),
    ]
    return [
        archive_table(
            session, store, name, cutoff, prefix=prefix, run_id=run_id, batch_size=batch_size, dry_run=dry_run
        )
        for name, cutoff in plan
    ]
