"""initial platform foundation

Foundation schema v0 (Phase 0). Person 1 owns its evolution.

Tables: identity (users), tenancy (organizations, clinics, doctors,
clinic_memberships, clinic_assignments), governed profile (clinic_profiles,
consent_records), assets, governance (approvals, audit_events), work
(work_items, notifications), reporting (metric_snapshots, report_artifacts).

On PostgreSQL, audit_events is made append-only with a trigger.

Revision ID: 0001
Revises:
Create Date: 2026-09-25 06:48:41.651631+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("cognito_sub", sa.String(length=64), nullable=True),
        sa.Column(
            "platform_role",
            sa.Enum(
                "platform_admin",
                "internal_manager",
                "internal_analyst",
                "client",
                name="platformrole",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_users_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("cognito_sub", name=op.f("uq_users_cognito_sub")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_organizations_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
    )
    op.create_table(
        "clinics",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address_line", sa.String(length=300), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("state", sa.String(length=100), nullable=True),
        sa.Column("postal_code", sa.String(length=20), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("website_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_clinics_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_clinics_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clinics")),
    )
    op.create_index(op.f("ix_clinics_organization_id"), "clinics", ["organization_id"], unique=False)
    op.create_table(
        "approvals",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column(
            "state",
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
        sa.Column("submitted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("assignee_user_id", sa.Uuid(), nullable=True),
        sa.Column("last_comment", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["assignee_user_id"],
            ["users.id"],
            name=op.f("fk_approvals_assignee_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_approvals_clinic_id_clinics"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name=op.f("fk_approvals_decided_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"],
            ["users.id"],
            name=op.f("fk_approvals_submitted_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
        sa.UniqueConstraint(
            "resource_type", "resource_id", name=op.f("uq_approvals_resource_type_resource_id")
        ),
    )
    op.create_index(op.f("ix_approvals_clinic_id"), "approvals", ["clinic_id"], unique=False)
    op.create_table(
        "assets",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "clinic_photo",
                "doctor_photo",
                "brand_asset",
                "logo",
                "audio",
                "video",
                "report",
                "generated_media",
                "document",
                name="assetkind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("mime_type", sa.String(length=127), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("previous_version_id", sa.Uuid(), nullable=True),
        sa.Column(
            "provenance",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending_upload",
                "uploaded",
                "failed",
                "deleted",
                name="assetstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
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
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_assets_clinic_id_clinics"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=op.f("fk_assets_owner_user_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["previous_version_id"],
            ["assets.id"],
            name=op.f("fk_assets_previous_version_id_assets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_assets_storage_key")),
    )
    op.create_index(op.f("ix_assets_clinic_id"), "assets", ["clinic_id"], unique=False)
    op.create_index("ix_assets_clinic_kind", "assets", ["clinic_id", "kind"], unique=False)
    op.create_table(
        "audit_events",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("clinic_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_audit_events_clinic_id_clinics"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_action"), "audit_events", ["action"], unique=False)
    op.create_index("ix_audit_events_clinic_time", "audit_events", ["clinic_id", "occurred_at"], unique=False)
    op.create_table(
        "clinic_assignments",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "account_manager",
                "analyst",
                name="assignmentrole",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"],
            ["users.id"],
            name=op.f("fk_clinic_assignments_assigned_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_clinic_assignments_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_clinic_assignments_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clinic_assignments")),
        sa.UniqueConstraint(
            "clinic_id", "user_id", "role", name=op.f("uq_clinic_assignments_clinic_id_user_id_role")
        ),
    )
    op.create_index(
        op.f("ix_clinic_assignments_clinic_id"), "clinic_assignments", ["clinic_id"], unique=False
    )
    op.create_index(op.f("ix_clinic_assignments_user_id"), "clinic_assignments", ["user_id"], unique=False)
    op.create_table(
        "clinic_memberships",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "owner",
                "admin",
                "doctor",
                "staff",
                name="clinicrole",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_clinic_memberships_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            name=op.f("fk_clinic_memberships_invited_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_clinic_memberships_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clinic_memberships")),
        sa.UniqueConstraint("clinic_id", "user_id", name=op.f("uq_clinic_memberships_clinic_id_user_id")),
    )
    op.create_index(
        op.f("ix_clinic_memberships_clinic_id"), "clinic_memberships", ["clinic_id"], unique=False
    )
    op.create_index(op.f("ix_clinic_memberships_user_id"), "clinic_memberships", ["user_id"], unique=False)
    op.create_table(
        "clinic_profiles",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column(
            "brand",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "audience",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "services",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "schedule",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_clinic_profiles_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_clinic_profiles_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("clinic_id", name=op.f("pk_clinic_profiles")),
    )
    op.create_table(
        "consent_records",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("consent_type", sa.String(length=64), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("granted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "evidence",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_consent_records_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            name=op.f("fk_consent_records_granted_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_records")),
    )
    op.create_index(op.f("ix_consent_records_clinic_id"), "consent_records", ["clinic_id"], unique=False)
    op.create_table(
        "doctors",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("specialty", sa.String(length=120), nullable=True),
        sa.Column("qualifications", sa.String(length=300), nullable=True),
        sa.Column("registration_number", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_doctors_clinic_id_clinics"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_doctors_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctors")),
    )
    op.create_index(op.f("ix_doctors_clinic_id"), "doctors", ["clinic_id"], unique=False)
    op.create_table(
        "metric_snapshots",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "google_business_profile",
                "google_search_console",
                "website_crawl",
                "instagram",
                "facebook",
                "youtube",
                "linkedin",
                "manual",
                name="datasource",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("metric_key", sa.String(length=128), nullable=False),
        sa.Column(
            "value",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ok",
                "stale",
                "error",
                "pending",
                name="snapshotstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_metric_snapshots_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingested_by_user_id"],
            ["users.id"],
            name=op.f("fk_metric_snapshots_ingested_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_snapshots")),
    )
    op.create_index(
        "ix_metric_snapshots_lookup",
        "metric_snapshots",
        ["clinic_id", "metric_key", "fetched_at"],
        unique=False,
    )
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("clinic_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_notifications_clinic_id_clinics"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index("ix_notifications_user_unread", "notifications", ["user_id", "read_at"], unique=False)
    op.create_table(
        "report_artifacts",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("report_type", sa.String(length=64), nullable=False),
        sa.Column("report_key", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "provenance",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
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
            ["asset_id"], ["assets.id"], name=op.f("fk_report_artifacts_asset_id_assets"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name=op.f("fk_report_artifacts_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_report_artifacts_owner_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_artifacts")),
        sa.UniqueConstraint(
            "clinic_id",
            "report_key",
            "version",
            name=op.f("uq_report_artifacts_clinic_id_report_key_version"),
        ),
    )
    op.create_index(op.f("ix_report_artifacts_clinic_id"), "report_artifacts", ["clinic_id"], unique=False)
    op.create_table(
        "work_items",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "todo",
                "in_progress",
                "blocked",
                "in_review",
                "done",
                "cancelled",
                name="workitemstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum(
                "low",
                "normal",
                "high",
                "urgent",
                name="workitempriority",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("source_team", sa.String(length=32), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["approvals.id"],
            name=op.f("fk_work_items_approval_id_approvals"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_work_items_clinic_id_clinics"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_work_items_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_work_items_owner_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_items")),
    )
    op.create_index(op.f("ix_work_items_clinic_id"), "work_items", ["clinic_id"], unique=False)
    op.create_index("ix_work_items_clinic_status", "work_items", ["clinic_id", "status"], unique=False)
    op.create_index(op.f("ix_work_items_owner_user_id"), "work_items", ["owner_user_id"], unique=False)

    # ---- audit_events is append-only (PostgreSQL only; SQLite is test-only) ----
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION audit_events_block_mutation() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'audit_events is append-only (% blocked)', TG_OP;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_block_mutation();
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
        op.execute("DROP FUNCTION IF EXISTS audit_events_block_mutation()")
    op.drop_index(op.f("ix_work_items_owner_user_id"), table_name="work_items")
    op.drop_index("ix_work_items_clinic_status", table_name="work_items")
    op.drop_index(op.f("ix_work_items_clinic_id"), table_name="work_items")
    op.drop_table("work_items")
    op.drop_index(op.f("ix_report_artifacts_clinic_id"), table_name="report_artifacts")
    op.drop_table("report_artifacts")
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_metric_snapshots_lookup", table_name="metric_snapshots")
    op.drop_table("metric_snapshots")
    op.drop_index(op.f("ix_doctors_clinic_id"), table_name="doctors")
    op.drop_table("doctors")
    op.drop_index(op.f("ix_consent_records_clinic_id"), table_name="consent_records")
    op.drop_table("consent_records")
    op.drop_table("clinic_profiles")
    op.drop_index(op.f("ix_clinic_memberships_user_id"), table_name="clinic_memberships")
    op.drop_index(op.f("ix_clinic_memberships_clinic_id"), table_name="clinic_memberships")
    op.drop_table("clinic_memberships")
    op.drop_index(op.f("ix_clinic_assignments_user_id"), table_name="clinic_assignments")
    op.drop_index(op.f("ix_clinic_assignments_clinic_id"), table_name="clinic_assignments")
    op.drop_table("clinic_assignments")
    op.drop_index("ix_audit_events_clinic_time", table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_action"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_assets_clinic_kind", table_name="assets")
    op.drop_index(op.f("ix_assets_clinic_id"), table_name="assets")
    op.drop_table("assets")
    op.drop_index(op.f("ix_approvals_clinic_id"), table_name="approvals")
    op.drop_table("approvals")
    op.drop_index(op.f("ix_clinics_organization_id"), table_name="clinics")
    op.drop_table("clinics")
    op.drop_table("organizations")
    op.drop_table("users")
