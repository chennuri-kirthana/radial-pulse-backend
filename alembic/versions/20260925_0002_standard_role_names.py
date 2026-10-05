"""standard role names (Platform Administrator / Digital Success Manager / Clinic Administrator)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-25

Data-preserving rename. Existing rows are MAPPED, never dropped (except exact duplicate
assignments, which only differed by the removed assignment role):

    users.platform_role
        platform_admin                      -> platform_administrator
        internal_manager, internal_analyst  -> digital_success_manager
        client                              -> clinic_user
    clinic_memberships.role
        owner, admin                        -> clinic_administrator
        doctor, staff                       -> clinic_team_member   (reserved role, NO access:
                                                                     fails closed until designed)
    clinic_assignments
        role column removed (a Digital Success Manager is simply assigned or not);
        duplicate (clinic_id, user_id) rows collapsed, keeping the active/oldest one.

Order for each column: drop CHECK → update values → add new CHECK, all in one transaction.
The downgrade maps back (lossy: all DSMs become internal_analyst, team members become staff).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _recheck(table: str, name: str, column: str, values: list[str]) -> None:
    allowed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(op.f(name), table, f"{column} IN ({allowed})")


def upgrade() -> None:
    # ---- users.platform_role -------------------------------------------------
    op.drop_constraint(op.f("ck_users_platformrole"), "users", type_="check")
    op.execute(
        """
        UPDATE users SET platform_role = CASE platform_role
            WHEN 'platform_admin'   THEN 'platform_administrator'
            WHEN 'internal_manager' THEN 'digital_success_manager'
            WHEN 'internal_analyst' THEN 'digital_success_manager'
            WHEN 'client'           THEN 'clinic_user'
            ELSE platform_role END
        """
    )
    _recheck(
        "users",
        "ck_users_platformrole",
        "platform_role",
        ["platform_administrator", "digital_success_manager", "clinic_user"],
    )

    # ---- clinic_memberships.role ---------------------------------------------
    op.drop_constraint(op.f("ck_clinic_memberships_clinicrole"), "clinic_memberships", type_="check")
    op.execute(
        """
        UPDATE clinic_memberships SET role = CASE role
            WHEN 'owner'  THEN 'clinic_administrator'
            WHEN 'admin'  THEN 'clinic_administrator'
            WHEN 'doctor' THEN 'clinic_team_member'
            WHEN 'staff'  THEN 'clinic_team_member'
            ELSE role END
        """
    )
    _recheck(
        "clinic_memberships",
        "ck_clinic_memberships_clinicrole",
        "role",
        ["clinic_administrator", "clinic_team_member"],
    )

    # ---- clinic_assignments: one row per (clinic, DSM) -------------------------
    op.execute(
        """
        DELETE FROM clinic_assignments WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY clinic_id, user_id ORDER BY is_active DESC, created_at, id
                ) AS rn
                FROM clinic_assignments
            ) ranked WHERE rn > 1
        )
        """
    )
    op.drop_constraint(
        op.f("uq_clinic_assignments_clinic_id_user_id_role"), "clinic_assignments", type_="unique"
    )
    op.drop_constraint(op.f("ck_clinic_assignments_assignmentrole"), "clinic_assignments", type_="check")
    op.drop_column("clinic_assignments", "role")
    op.create_unique_constraint(
        op.f("uq_clinic_assignments_clinic_id_user_id"), "clinic_assignments", ["clinic_id", "user_id"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_clinic_assignments_clinic_id_user_id"), "clinic_assignments", type_="unique")
    op.add_column(
        "clinic_assignments",
        sa.Column("role", sa.String(32), nullable=False, server_default="analyst"),
    )
    op.alter_column("clinic_assignments", "role", server_default=None)
    _recheck(
        "clinic_assignments", "ck_clinic_assignments_assignmentrole", "role", ["account_manager", "analyst"]
    )
    op.create_unique_constraint(
        op.f("uq_clinic_assignments_clinic_id_user_id_role"),
        "clinic_assignments",
        ["clinic_id", "user_id", "role"],
    )

    op.drop_constraint(op.f("ck_clinic_memberships_clinicrole"), "clinic_memberships", type_="check")
    op.execute(
        "UPDATE clinic_memberships SET role = CASE role "
        "WHEN 'clinic_administrator' THEN 'admin' WHEN 'clinic_team_member' THEN 'staff' ELSE role END"
    )
    _recheck(
        "clinic_memberships",
        "ck_clinic_memberships_clinicrole",
        "role",
        ["owner", "admin", "doctor", "staff"],
    )

    op.drop_constraint(op.f("ck_users_platformrole"), "users", type_="check")
    op.execute(
        "UPDATE users SET platform_role = CASE platform_role "
        "WHEN 'platform_administrator' THEN 'platform_admin' "
        "WHEN 'digital_success_manager' THEN 'internal_analyst' "
        "WHEN 'clinic_user' THEN 'client' ELSE platform_role END"
    )
    _recheck(
        "users",
        "ck_users_platformrole",
        "platform_role",
        ["platform_admin", "internal_manager", "internal_analyst", "client"],
    )
