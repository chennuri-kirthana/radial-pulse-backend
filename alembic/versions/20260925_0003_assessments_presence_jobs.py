"""digital presence assessment, presence profiles, background jobs

Additive only (new tables + one nullable column), safe to deploy while the previous app
version is running:
* assessments / assessment_components / assessment_findings — the ONE user-facing
  Digital Presence Assessment and its engine-produced parts (with evidence)
* presence_profiles — generic "where is this clinic online" table (platform column)
* background_jobs — status/idempotency record for queued work
* report_artifacts.assessment_id — an exported file can point at its assessment

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-25 09:13:56.018894+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assessments",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "completed",
                "partial",
                "failed",
                name="assessmentstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("methodology_version", sa.String(length=32), nullable=False),
        sa.Column("overall_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "approval_state",
            sa.Enum(
                "draft",
                "submitted",
                "approved",
                "rejected",
                "redo_requested",
                name="approvalstate",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "publication_state",
            sa.Enum(
                "unpublished",
                "published",
                "retracted",
                name="publicationstate",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_assessments_clinic_id_clinics"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_assessments_requested_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessments")),
        sa.UniqueConstraint("clinic_id", "sequence", name=op.f("uq_assessments_clinic_id_sequence")),
    )
    op.create_index(op.f("ix_assessments_clinic_id"), "assessments", ["clinic_id"], unique=False)
    op.create_table(
        "background_jobs",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column(
            "job_type",
            sa.Enum("assessment.run", name="jobtype", native_enum=False, create_constraint=True, length=40),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                name="jobstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_background_jobs_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_background_jobs_requested_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_background_jobs")),
    )
    op.create_index(op.f("ix_background_jobs_clinic_id"), "background_jobs", ["clinic_id"], unique=False)
    op.create_index("ix_background_jobs_status", "background_jobs", ["status", "created_at"], unique=False)
    op.create_table(
        "presence_profiles",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column(
            "platform",
            sa.Enum(
                "website",
                "google_business_profile",
                "instagram",
                "facebook",
                "youtube",
                "linkedin",
                "x",
                "practo",
                "justdial",
                "other",
                name="presenceplatform",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column(
            "verification",
            sa.Enum(
                "unverified",
                "confirmed",
                "rejected",
                name="presenceverification",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("discovered_by", sa.String(length=128), nullable=False),
        sa.Column(
            "evidence",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("verified_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_presence_profiles_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["verified_by_user_id"],
            ["users.id"],
            name=op.f("fk_presence_profiles_verified_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_presence_profiles")),
        sa.UniqueConstraint(
            "clinic_id", "platform", "url", name=op.f("uq_presence_profiles_clinic_id_platform_url")
        ),
    )
    op.create_index(op.f("ix_presence_profiles_clinic_id"), "presence_profiles", ["clinic_id"], unique=False)
    op.create_table(
        "assessment_components",
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column(
            "key",
            sa.Enum(
                "website",
                "google_business_profile",
                "local_search",
                "search_readiness",
                "social_presence",
                "competitor_benchmark",
                name="assessmentcomponentkey",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "completed",
                "failed",
                "not_available",
                name="componentstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("engine_name", sa.String(length=64), nullable=True),
        sa.Column("engine_version", sa.String(length=32), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_reason", sa.String(length=200), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["assessments.id"],
            name=op.f("fk_assessment_components_assessment_id_assessments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_assessment_components_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_components")),
        sa.UniqueConstraint("assessment_id", "key", name=op.f("uq_assessment_components_assessment_id_key")),
    )
    op.create_index(
        op.f("ix_assessment_components_clinic_id"), "assessment_components", ["clinic_id"], unique=False
    )
    op.create_table(
        "assessment_findings",
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("component_id", sa.Uuid(), nullable=False),
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=96), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "priority",
            sa.Enum(
                "critical",
                "high",
                "medium",
                "low",
                "info",
                name="findingpriority",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column(
            "evidence",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["assessments.id"],
            name=op.f("fk_assessment_findings_assessment_id_assessments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_assessment_findings_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["component_id"],
            ["assessment_components.id"],
            name=op.f("fk_assessment_findings_component_id_assessment_components"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_findings")),
    )
    op.create_index(
        op.f("ix_assessment_findings_assessment_id"), "assessment_findings", ["assessment_id"], unique=False
    )
    op.create_index(
        "ix_assessment_findings_component", "assessment_findings", ["component_id", "priority"], unique=False
    )
    op.add_column("report_artifacts", sa.Column("assessment_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_report_artifacts_assessment_id_assessments"),
        "report_artifacts",
        "assessments",
        ["assessment_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_report_artifacts_assessment_id_assessments"), "report_artifacts", type_="foreignkey"
    )
    op.drop_column("report_artifacts", "assessment_id")
    op.drop_index("ix_assessment_findings_component", table_name="assessment_findings")
    op.drop_index(op.f("ix_assessment_findings_assessment_id"), table_name="assessment_findings")
    op.drop_table("assessment_findings")
    op.drop_index(op.f("ix_assessment_components_clinic_id"), table_name="assessment_components")
    op.drop_table("assessment_components")
    op.drop_index(op.f("ix_presence_profiles_clinic_id"), table_name="presence_profiles")
    op.drop_table("presence_profiles")
    op.drop_index("ix_background_jobs_status", table_name="background_jobs")
    op.drop_index(op.f("ix_background_jobs_clinic_id"), table_name="background_jobs")
    op.drop_table("background_jobs")
    op.drop_index(op.f("ix_assessments_clinic_id"), table_name="assessments")
    op.drop_table("assessments")
