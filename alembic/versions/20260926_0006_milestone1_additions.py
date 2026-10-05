"""milestone 1 additions: clinic stages, one DSM per clinic, clinic details, work item links

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-26

See docs/architecture/database-schema.md (v1.0). In plain words:

* users:              + phone, + last_invited_at
* clinics:            + specialty, description, email, latitude/longitude, cover photo,
                      + stage (5 steps) + stage_changed_at, + archived_reason
                      rules: archiving needs a reason; latitude/longitude both set or both empty
* clinic_assignments: at most ONE active DSM per clinic (older extra active rows are ended)
* practitioners:      + bio, + is_primary (one main practitioner per clinic)
* work_items:         + area, finding_code, source_finding_id, completed_at
                      rule: one OPEN work item per finding code per clinic
* background_jobs:    job type 'presence.discover' allowed (reserved)
* NEW clinic_stage_history: append-only diary of stage moves, under row-level security

Existing data is kept and back-filled (every clinic starts at 'prospective_client' with one
history row; the oldest active practitioner becomes the main one).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "radial_app"
STAGES = [
    "prospective_client",
    "profile_enriched",
    "assessment_completed",
    "client_discussion",
    "active_client",
]
WORK_AREAS = [
    "website",
    "google_business_profile",
    "local_search",
    "search_readiness",
    "social_presence",
    "competitor_benchmark",
    "clinic_profile",
    "other",
]
TENANT_PREDICATE = "rp_all_clinics() OR clinic_id = ANY (rp_clinic_ids())"
OPEN_FINDING = "finding_code IS NOT NULL AND status NOT IN ('done', 'cancelled')"


def _in(column: str, values: list[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    # ---- users ------------------------------------------------------------------
    op.add_column("users", sa.Column("phone", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("last_invited_at", sa.DateTime(timezone=True), nullable=True))

    # ---- clinics ----------------------------------------------------------------
    op.add_column("clinics", sa.Column("specialty", sa.String(length=200), nullable=True))
    op.add_column("clinics", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("clinics", sa.Column("email", sa.String(length=320), nullable=True))
    op.add_column("clinics", sa.Column("latitude", sa.Numeric(9, 6), nullable=True))
    op.add_column("clinics", sa.Column("longitude", sa.Numeric(9, 6), nullable=True))
    op.add_column("clinics", sa.Column("cover_asset_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_clinics_cover_asset_id_assets"), "clinics", "assets", ["cover_asset_id"], ["id"],
        ondelete="SET NULL",
    )  # fmt: skip
    op.add_column(
        "clinics",
        sa.Column("stage", sa.String(length=32), nullable=False, server_default="prospective_client"),
    )
    op.add_column(
        "clinics",
        sa.Column(
            "stage_changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.alter_column("clinics", "stage", server_default=None)
    op.alter_column("clinics", "stage_changed_at", server_default=None)
    op.create_check_constraint(op.f("ck_clinics_clinicstage"), "clinics", _in("stage", STAGES))
    op.create_index(op.f("ix_clinics_stage"), "clinics", ["stage"], unique=False)

    op.add_column("clinics", sa.Column("archived_reason", sa.Text(), nullable=True))
    # Clinics archived before this release have no reason: give them one so the rule can hold.
    op.execute(
        "UPDATE clinics SET archived_reason = 'Archived before reasons were recorded' "
        "WHERE NOT is_active AND archived_reason IS NULL"
    )
    op.create_check_constraint(
        op.f("ck_clinics_archive_reason"),
        "clinics",
        "is_active OR (archived_reason IS NOT NULL AND length(trim(archived_reason)) > 0)",
    )
    op.create_check_constraint(
        op.f("ck_clinics_lat_lng_pair"), "clinics", "(latitude IS NULL) = (longitude IS NULL)"
    )

    # ---- clinic_stage_history (NEW, append-only, RLS) ----------------------------
    op.create_table(
        "clinic_stage_history",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("from_stage", sa.String(length=32), nullable=True),
        sa.Column("to_stage", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(_in("from_stage", STAGES), name=op.f("ck_clinic_stage_history_clinicstage_from")),
        sa.CheckConstraint(_in("to_stage", STAGES), name=op.f("ck_clinic_stage_history_clinicstage_to")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_clinic_stage_history_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"], ["users.id"], name=op.f("fk_clinic_stage_history_changed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clinic_stage_history")),
    )  # fmt: skip
    op.create_index(
        "ix_clinic_stage_history_clinic_time",
        "clinic_stage_history",
        ["clinic_id", "changed_at"],
        unique=False,
    )
    # Every existing clinic gets its first diary row.
    op.execute(
        "INSERT INTO clinic_stage_history (id, clinic_id, from_stage, to_stage, changed_at) "
        "SELECT gen_random_uuid(), id, NULL, 'prospective_client', created_at FROM clinics"
    )
    op.execute("ALTER TABLE clinic_stage_history ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON clinic_stage_history TO {APP_ROLE} "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )
    # DML grants come from 0004's ALTER DEFAULT PRIVILEGES; take back UPDATE/DELETE (append-only).
    op.execute(f"GRANT SELECT, INSERT ON clinic_stage_history TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON clinic_stage_history FROM {APP_ROLE}")

    # ---- clinic_assignments: one active DSM per clinic ----------------------------
    op.execute(
        """
        UPDATE clinic_assignments SET is_active = false, updated_at = now() WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (PARTITION BY clinic_id ORDER BY created_at, id) AS rn
                FROM clinic_assignments WHERE is_active
            ) ranked WHERE rn > 1
        )
        """
    )
    op.create_index(
        "uq_clinic_assignments_one_active", "clinic_assignments", ["clinic_id"], unique=True,
        postgresql_where=sa.text("is_active"),
    )  # fmt: skip

    # ---- practitioners ------------------------------------------------------------
    op.add_column("practitioners", sa.Column("bio", sa.Text(), nullable=True))
    op.add_column(
        "practitioners", sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.alter_column("practitioners", "is_primary", server_default=None)
    op.execute(
        """
        UPDATE practitioners SET is_primary = true WHERE id IN (
            SELECT DISTINCT ON (clinic_id) id FROM practitioners
            WHERE is_active ORDER BY clinic_id, created_at, id
        )
        """
    )
    op.create_index(
        "uq_practitioners_one_primary", "practitioners", ["clinic_id"], unique=True,
        postgresql_where=sa.text("is_primary AND is_active"),
    )  # fmt: skip

    # ---- work_items -----------------------------------------------------------------
    op.add_column(
        "work_items", sa.Column("area", sa.String(length=40), nullable=False, server_default="other")
    )
    op.alter_column("work_items", "area", server_default=None)
    op.create_check_constraint(op.f("ck_work_items_workarea"), "work_items", _in("area", WORK_AREAS))
    op.add_column("work_items", sa.Column("finding_code", sa.String(length=96), nullable=True))
    op.add_column("work_items", sa.Column("source_finding_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_work_items_source_finding_id_assessment_findings"), "work_items", "assessment_findings",
        ["source_finding_id"], ["id"], ondelete="SET NULL",
    )  # fmt: skip
    op.add_column("work_items", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE work_items SET completed_at = updated_at WHERE status = 'done'")
    op.create_index(
        "ix_work_items_clinic_area_status", "work_items", ["clinic_id", "area", "status"], unique=False
    )
    op.create_index(
        "uq_work_items_one_open_per_finding", "work_items", ["clinic_id", "finding_code"], unique=True,
        postgresql_where=sa.text(OPEN_FINDING),
    )  # fmt: skip

    # ---- background_jobs: reserve 'presence.discover' ------------------------------------
    op.drop_constraint(op.f("ck_background_jobs_jobtype"), "background_jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_background_jobs_jobtype"),
        "background_jobs",
        _in("job_type", ["assessment.run", "presence.discover"]),
    )


def downgrade() -> None:
    op.execute("DELETE FROM background_jobs WHERE job_type = 'presence.discover'")
    op.drop_constraint(op.f("ck_background_jobs_jobtype"), "background_jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_background_jobs_jobtype"), "background_jobs", _in("job_type", ["assessment.run"])
    )

    op.drop_index("uq_work_items_one_open_per_finding", table_name="work_items")
    op.drop_index("ix_work_items_clinic_area_status", table_name="work_items")
    op.drop_column("work_items", "completed_at")
    op.drop_constraint(
        op.f("fk_work_items_source_finding_id_assessment_findings"), "work_items", type_="foreignkey"
    )
    op.drop_column("work_items", "source_finding_id")
    op.drop_column("work_items", "finding_code")
    op.drop_constraint(op.f("ck_work_items_workarea"), "work_items", type_="check")
    op.drop_column("work_items", "area")

    op.drop_index("uq_practitioners_one_primary", table_name="practitioners")
    op.drop_column("practitioners", "is_primary")
    op.drop_column("practitioners", "bio")

    op.drop_index("uq_clinic_assignments_one_active", table_name="clinic_assignments")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON clinic_stage_history")
    op.drop_index("ix_clinic_stage_history_clinic_time", table_name="clinic_stage_history")
    op.drop_table("clinic_stage_history")

    op.drop_constraint(op.f("ck_clinics_lat_lng_pair"), "clinics", type_="check")
    op.drop_constraint(op.f("ck_clinics_archive_reason"), "clinics", type_="check")
    op.drop_column("clinics", "archived_reason")
    op.drop_index(op.f("ix_clinics_stage"), table_name="clinics")
    op.drop_constraint(op.f("ck_clinics_clinicstage"), "clinics", type_="check")
    op.drop_column("clinics", "stage_changed_at")
    op.drop_column("clinics", "stage")
    op.drop_constraint(op.f("fk_clinics_cover_asset_id_assets"), "clinics", type_="foreignkey")
    for column in ("cover_asset_id", "longitude", "latitude", "email", "description", "specialty"):
        op.drop_column("clinics", column)

    op.drop_column("users", "last_invited_at")
    op.drop_column("users", "phone")
