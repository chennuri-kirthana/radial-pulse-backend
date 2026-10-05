"""a practitioner can work at several clinics (branches) of the same business

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-27

Before: one ``practitioners`` row per clinic, so a doctor at 2 branches was 2 records.
After:

* practitioners          the PERSON: one record per person per business (organization_id)
* clinic_practitioners   NEW: which clinics they work at (+ is_primary, is_active per clinic)

Data is kept: every existing practitioner gets its business from its clinic and one link row
with the same is_primary / is_active. (Existing duplicates are NOT merged automatically: the
team links the right record through the API when it knows two rows are the same person.)

Row-level security:
* clinic_practitioners   the usual clinic rule (tenant_isolation)
* practitioners          visible if linked to a clinic in scope, or owned by the business of a
                         clinic in scope (so a DSM can link a doctor from a sibling branch)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "radial_app"
IN_SCOPE = "rp_all_clinics() OR clinic_id = ANY (rp_clinic_ids())"
SAME_BUSINESS_IN_SCOPE = (
    "EXISTS (SELECT 1 FROM clinics c WHERE c.organization_id = practitioners.organization_id "
    "AND c.id = ANY (rp_clinic_ids()))"
)
PRACTITIONER_VISIBLE = (
    "rp_all_clinics() "
    "OR EXISTS (SELECT 1 FROM clinic_practitioners cp WHERE cp.practitioner_id = practitioners.id "
    "AND cp.clinic_id = ANY (rp_clinic_ids())) "
    f"OR {SAME_BUSINESS_IN_SCOPE}"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # ---- the person belongs to a business --------------------------------------
    op.add_column("practitioners", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.execute(
        "UPDATE practitioners p SET organization_id = c.organization_id FROM clinics c WHERE c.id = p.clinic_id"
    )
    op.alter_column("practitioners", "organization_id", nullable=False)
    op.create_foreign_key(
        "fk_practitioners_organization_id_organizations",
        "practitioners",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_practitioners_organization_id", "practitioners", ["organization_id"])

    # ---- the link table -----------------------------------------------------------
    op.create_table(
        "clinic_practitioners",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("practitioner_id", sa.Uuid(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name="fk_clinic_practitioners_clinic_id_clinics",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["practitioner_id"],
            ["practitioners.id"],
            name="fk_clinic_practitioners_practitioner_id_practitioners",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_clinic_practitioners"),
        sa.UniqueConstraint(
            "clinic_id", "practitioner_id", name="uq_clinic_practitioners_clinic_id_practitioner_id"
        ),
    )
    op.create_index("ix_clinic_practitioners_clinic_id", "clinic_practitioners", ["clinic_id"])
    op.create_index("ix_clinic_practitioners_practitioner_id", "clinic_practitioners", ["practitioner_id"])
    op.execute(
        """
        INSERT INTO clinic_practitioners (id, clinic_id, practitioner_id, is_primary, is_active,
                                          created_at, updated_at)
        SELECT gen_random_uuid(), clinic_id, id, is_primary, is_active, created_at, updated_at
        FROM practitioners
        """
    )
    op.create_index(
        "uq_clinic_practitioners_one_primary",
        "clinic_practitioners",
        ["clinic_id"],
        unique=True,
        postgresql_where=sa.text("is_primary AND is_active"),
    )

    # ---- the person no longer carries clinic columns ----------------------------------
    if _is_postgres():
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON practitioners")
    op.drop_index("uq_practitioners_one_primary", table_name="practitioners")
    op.drop_index("ix_practitioners_clinic_id", table_name="practitioners")
    op.drop_constraint("fk_practitioners_clinic_id_clinics", "practitioners", type_="foreignkey")
    op.drop_column("practitioners", "clinic_id")
    op.drop_column("practitioners", "is_primary")
    op.drop_column("practitioners", "is_active")

    if _is_postgres():
        op.execute("ALTER TABLE clinic_practitioners ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON clinic_practitioners TO {APP_ROLE} "
            f"USING ({IN_SCOPE}) WITH CHECK ({IN_SCOPE})"
        )
        op.execute(
            f"CREATE POLICY practitioners_read ON practitioners FOR SELECT TO {APP_ROLE} "
            f"USING ({PRACTITIONER_VISIBLE})"
        )
        op.execute(
            f"CREATE POLICY practitioners_update ON practitioners FOR UPDATE TO {APP_ROLE} "
            f"USING ({PRACTITIONER_VISIBLE}) WITH CHECK ({PRACTITIONER_VISIBLE})"
        )
        op.execute(
            f"CREATE POLICY practitioners_insert ON practitioners FOR INSERT TO {APP_ROLE} "
            f"WITH CHECK (rp_all_clinics() OR {SAME_BUSINESS_IN_SCOPE})"
        )


def downgrade() -> None:
    if _is_postgres():
        for name in ("practitioners_read", "practitioners_update", "practitioners_insert"):
            op.execute(f"DROP POLICY IF EXISTS {name} ON practitioners")
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON clinic_practitioners")

    op.add_column("practitioners", sa.Column("clinic_id", sa.Uuid(), nullable=True))
    op.add_column(
        "practitioners", sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column(
        "practitioners", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    # A person linked to several clinics becomes one row per clinic again: the first link keeps
    # the original row, every other link gets a copy.
    op.execute(
        """
        WITH ranked AS (
            SELECT cp.*, row_number() OVER (PARTITION BY practitioner_id ORDER BY created_at, id) AS rn
            FROM clinic_practitioners cp
        )
        UPDATE practitioners p SET clinic_id = r.clinic_id, is_primary = r.is_primary, is_active = r.is_active
        FROM ranked r WHERE r.practitioner_id = p.id AND r.rn = 1
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT cp.*, row_number() OVER (PARTITION BY practitioner_id ORDER BY created_at, id) AS rn
            FROM clinic_practitioners cp
        )
        INSERT INTO practitioners (id, clinic_id, full_name, specialty, qualifications,
                                   registration_number, bio, user_id, is_primary, is_active,
                                   organization_id, created_at, updated_at)
        SELECT gen_random_uuid(), r.clinic_id, p.full_name, p.specialty, p.qualifications,
               p.registration_number, p.bio, p.user_id, r.is_primary, r.is_active,
               p.organization_id, r.created_at, r.updated_at
        FROM ranked r JOIN practitioners p ON p.id = r.practitioner_id
        WHERE r.rn > 1
        """
    )
    # A practitioner with no clinic link cannot exist in the old shape.
    op.execute("DELETE FROM practitioners WHERE clinic_id IS NULL")
    op.alter_column("practitioners", "clinic_id", nullable=False)
    op.alter_column("practitioners", "is_primary", server_default=None)
    op.alter_column("practitioners", "is_active", server_default=None)
    op.create_foreign_key(
        "fk_practitioners_clinic_id_clinics",
        "practitioners",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_practitioners_clinic_id", "practitioners", ["clinic_id"])
    op.create_index(
        "uq_practitioners_one_primary",
        "practitioners",
        ["clinic_id"],
        unique=True,
        postgresql_where=sa.text("is_primary AND is_active"),
    )
    op.drop_table("clinic_practitioners")
    op.drop_index("ix_practitioners_organization_id", table_name="practitioners")
    op.drop_constraint("fk_practitioners_organization_id_organizations", "practitioners", type_="foreignkey")
    op.drop_column("practitioners", "organization_id")
    if _is_postgres():
        op.execute(
            f"CREATE POLICY tenant_isolation ON practitioners TO {APP_ROLE} USING ({IN_SCOPE}) WITH CHECK ({IN_SCOPE})"
        )
