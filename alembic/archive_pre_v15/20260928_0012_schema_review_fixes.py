"""schema review fixes: missing indexes, duplicate indexes, one running assessment, data rules

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-28

In plain words (docs/architecture/schema-review-2026-09.md):

1. **Indexes for links that had none.** When a parent row is deleted or a child is looked up by
   its link, PostgreSQL must find the children. Without an index it reads the WHOLE child table.
   The worst one: every assessment re-run deletes the old findings, and for EACH deleted finding
   the database scanned all of ``work_items`` (``source_finding_id``). Partial indexes
   (``WHERE ΓÇª IS NOT NULL``) keep them small: most rows have no link.

2. **Duplicate indexes removed.** 10 single-column ``clinic_id`` / ``user_id`` indexes were already
   covered by a unique key or a bigger index that starts with the same column. Each one only slowed
   down every insert and update.

3. **Notifications list index.** The bell list is "my notifications, newest first". The old index
   ``(user_id, read_at)`` could not give that order, so PostgreSQL sorted every time.

4. **One running assessment per clinic.** The app checked "is one already running?" and then
   inserted. Two clicks at the same moment both passed the check. Now the database refuses the
   second one (and the API answers 409 instead of 500).

5. **Data rules (CHECK constraints)** the app already follows, now guaranteed by the database:
   scores 0 to 100, confidence 0 to 1, positive sizes / versions / counters, "finished after started",
   latitude / longitude ranges, 2-letter UPPER-case country, lower-case emails, a stage change
   must change the stage, a file is not its own previous version, and "done" work items (and
   only those) have ``completed_at``.

Existing rows: lower-case emails and upper-case countries are fixed automatically when that is
safe, and ``completed_at`` is filled / cleared to match the status. Anything that cannot be fixed
safely stops the migration with a list of the rows to fix.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (index name, table, columns, only rows where ΓÇª) ΓÇö indexes for links (foreign keys) and lists.
NEW_INDEXES = [
    ("ix_work_items_source_finding_id", "work_items", ["source_finding_id"], "source_finding_id IS NOT NULL"),
    ("ix_work_items_approval_id", "work_items", ["approval_id"], "approval_id IS NOT NULL"),
    ("ix_assessment_findings_clinic_id", "assessment_findings", ["clinic_id"], None),
    ("ix_notifications_clinic_id", "notifications", ["clinic_id"], "clinic_id IS NOT NULL"),
    ("ix_report_artifacts_assessment_id", "report_artifacts", ["assessment_id"], "assessment_id IS NOT NULL"),
    ("ix_report_artifacts_asset_id", "report_artifacts", ["asset_id"], "asset_id IS NOT NULL"),
    ("ix_chat_messages_attachment_asset_id", "chat_messages", ["attachment_asset_id"],
     "attachment_asset_id IS NOT NULL"),
    ("ix_assets_previous_version_id", "assets", ["previous_version_id"], "previous_version_id IS NOT NULL"),
    ("ix_clinics_cover_asset_id", "clinics", ["cover_asset_id"], "cover_asset_id IS NOT NULL"),
    ("ix_notifications_user_created", "notifications", ["user_id", "created_at", "id"], None),
    ("ix_notifications_unread", "notifications", ["user_id", "created_at"], "read_at IS NULL"),
]  # fmt: skip

#: (index name, table, columns) ΓÇö duplicates removed. The comment says what already covers it.
DROPPED_INDEXES = [
    ("ix_assessments_clinic_id", "assessments", ["clinic_id"]),  # uq (clinic_id, sequence)
    ("ix_assets_clinic_id", "assets", ["clinic_id"]),  # ix (clinic_id, kind)
    ("ix_clinic_assignments_clinic_id", "clinic_assignments", ["clinic_id"]),  # uq (clinic_id, user_id)
    ("ix_clinic_memberships_clinic_id", "clinic_memberships", ["clinic_id"]),  # uq (clinic_id, user_id)
    (
        "ix_clinic_practitioners_clinic_id",
        "clinic_practitioners",
        ["clinic_id"],
    ),  # uq (clinic_id, practitioner_id)
    ("ix_notification_preferences_user_id", "notification_preferences", ["user_id"]),  # uq (user_id, ΓÇª)
    ("ix_platform_connections_clinic_id", "platform_connections", ["clinic_id"]),  # uq (clinic_id, platform)
    ("ix_presence_profiles_clinic_id", "presence_profiles", ["clinic_id"]),  # uq (clinic_id, platform, url)
    (
        "ix_report_artifacts_clinic_id",
        "report_artifacts",
        ["clinic_id"],
    ),  # uq (clinic_id, report_key, version)
    ("ix_work_items_clinic_id", "work_items", ["clinic_id"]),  # ix (clinic_id, status)
    ("ix_notifications_user_unread", "notifications", ["user_id", "read_at"]),  # replaced (section 3)
]

ONE_RUNNING = "uq_assessments_one_in_progress"
RUNNING = "status IN ('queued', 'running')"

#: (constraint name, table, rule). Full names: the naming convention is ck_<table>_<name>.
CHECKS = [
    ("ck_users_email_lowercase", "users", "email = lower(trim(email))"),
    ("ck_clinics_country_code", "clinics", "country ~ '^[A-Z]{2}$'"),
    ("ck_clinics_latitude_range", "clinics", "latitude BETWEEN -90 AND 90"),
    ("ck_clinics_longitude_range", "clinics", "longitude BETWEEN -180 AND 180"),
    ("ck_assessments_sequence_positive", "assessments", "sequence >= 1"),
    ("ck_assessments_score_range", "assessments", "overall_score BETWEEN 0 AND 100"),
    ("ck_assessments_finished_after_start", "assessments", "completed_at >= started_at"),
    ("ck_assessment_components_score_range", "assessment_components", "score BETWEEN 0 AND 100"),
    ("ck_presence_profiles_confidence_range", "presence_profiles", "confidence BETWEEN 0 AND 1"),
    ("ck_assets_size_not_negative", "assets", "size_bytes >= 0"),
    ("ck_assets_version_positive", "assets", "version >= 1"),
    ("ck_assets_not_own_previous", "assets", "previous_version_id <> id"),
    ("ck_report_artifacts_version_positive", "report_artifacts", "version >= 1"),
    ("ck_clinic_profiles_version_positive", "clinic_profiles", "version >= 1"),
    ("ck_background_jobs_attempts_not_negative", "background_jobs", "attempts >= 0"),
    ("ck_background_jobs_max_attempts_positive", "background_jobs", "max_attempts >= 1"),
    ("ck_background_jobs_finished_after_start", "background_jobs", "finished_at >= started_at"),
    ("ck_metric_snapshots_retry_count_not_negative", "metric_snapshots", "retry_count >= 0"),
    ("ck_consent_records_revoked_after_granted", "consent_records", "revoked_at >= granted_at"),
    (
        "ck_clinic_stage_history_stage_changes",
        "clinic_stage_history",
        "from_stage IS NULL OR from_stage <> to_stage",
    ),
    ("ck_work_items_completed_when_done", "work_items", "(status = 'done') = (completed_at IS NOT NULL)"),
]


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _scalar(sql: str) -> int:
    return int(op.get_bind().execute(sa.text(sql)).scalar() or 0)


def _fix_what_is_safe() -> None:
    # Emails: lower-case + trim, unless that would clash with another account.
    op.execute(
        """
        UPDATE users u SET email = lower(trim(u.email))
        WHERE u.email <> lower(trim(u.email))
          AND NOT EXISTS (SELECT 1 FROM users o WHERE o.id <> u.id AND o.email = lower(trim(u.email)))
        """
    )
    # Countries: 'in' ΓåÆ 'IN'.
    op.execute("UPDATE clinics SET country = upper(trim(country)) WHERE country <> upper(trim(country))")
    # Work items: completed_at matches the status.
    op.execute(
        "UPDATE work_items SET completed_at = updated_at WHERE status = 'done' AND completed_at IS NULL"
    )
    op.execute(
        "UPDATE work_items SET completed_at = NULL WHERE status <> 'done' AND completed_at IS NOT NULL"
    )


def _check_existing_data() -> None:
    problems = []
    for name, table, rule in CHECKS:
        # A CHECK passes when the rule is NULL (e.g. no score yet), so count only real FALSE.
        n = _scalar(f"SELECT count(*) FROM {table} WHERE NOT coalesce(({rule}), true)")
        if n:
            problems.append(f"{n} row(s) in {table} break {name}: {rule}")
    n = _scalar(
        f"SELECT count(*) FROM (SELECT clinic_id FROM assessments WHERE {RUNNING} "
        "GROUP BY clinic_id HAVING count(*) > 1) x"
    )
    if n:
        problems.append(
            f"{n} clinic(s) have more than one queued/running assessment ΓÇö mark the extras failed"
        )
    if problems:
        raise RuntimeError("Migration 0012 stopped; fix these rows first:\n  " + "\n  ".join(problems))


def upgrade() -> None:
    if _is_postgres():
        _fix_what_is_safe()
        _check_existing_data()

    for name, table, cols, where in NEW_INDEXES:
        op.create_index(name, table, cols, postgresql_where=sa.text(where) if where else None)
    for name, table, _ in DROPPED_INDEXES:
        op.drop_index(name, table_name=table)

    op.create_index(ONE_RUNNING, "assessments", ["clinic_id"], unique=True, postgresql_where=sa.text(RUNNING))

    for name, table, rule in CHECKS:
        op.create_check_constraint(op.f(name), table, sa.text(rule))  # op.f: name is already final


def downgrade() -> None:
    for name, table, _ in reversed(CHECKS):
        op.drop_constraint(op.f(name), table, type_="check")
    op.drop_index(ONE_RUNNING, table_name="assessments")
    for name, table, cols in DROPPED_INDEXES:
        op.create_index(name, table, cols)
    for name, table, _, _ in reversed(NEW_INDEXES):
        op.drop_index(name, table_name=table)
