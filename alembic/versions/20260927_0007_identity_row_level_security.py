"""row-level security on the people tables (users, organizations, memberships, assignments, notifications)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-27

Until now these five tables were protected by the application only. Now PostgreSQL also
refuses rows a person should not see. In plain words:

* users               you; people of the clinics in scope; accounts you created;
                      Radial Pulse staff (only when YOU are staff); everyone for the Admin.
                      New accounts: anyone may create a clinic_user; only the Admin creates staff.
* clinic_memberships  rows of clinics in scope, and your own rows (needed at sign-in)
* clinic_assignments  same
* organizations       businesses that own a clinic in scope, or that you created
* notifications       only your own (anyone may SEND one inside a clinic in scope)

Nothing is ever deleted from these tables by the app (no DELETE policy = no deletes).

Who is asking comes from two new transaction-local settings set by app/db/tenant.py:
``app.user_id`` and ``app.is_staff`` (next to the existing ``app.clinic_ids`` / ``app.all_clinics``).

Sign-in and "add team member" must look an account up BEFORE it is visible. Two small
SECURITY DEFINER functions do exactly that and return only an id (and a role):
``rp_user_id_by_sub(sub)`` and ``rp_user_by_email(email)``.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "radial_app"
IN_SCOPE = "rp_all_clinics() OR clinic_id = ANY (rp_clinic_ids())"
MINE_OR_IN_SCOPE = f"{IN_SCOPE} OR user_id = rp_user_id()"

USER_VISIBLE = """
    rp_all_clinics()
    OR id = rp_user_id()
    OR created_by_user_id = rp_user_id()
    OR (rp_is_staff() AND platform_role IN ('platform_administrator', 'digital_success_manager'))
    OR EXISTS (SELECT 1 FROM clinic_memberships m
               WHERE m.user_id = users.id AND m.clinic_id = ANY (rp_clinic_ids()))
    OR EXISTS (SELECT 1 FROM clinic_assignments a
               WHERE a.user_id = users.id AND a.clinic_id = ANY (rp_clinic_ids()))
"""

ORG_VISIBLE = """
    rp_all_clinics()
    OR created_by_user_id = rp_user_id()
    OR EXISTS (SELECT 1 FROM clinics c
               WHERE c.organization_id = organizations.id AND c.id = ANY (rp_clinic_ids()))
"""


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    # ---- who is asking ---------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION rp_user_id() RETURNS uuid LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION rp_is_staff() RETURNS boolean LANGUAGE sql STABLE AS
        $$ SELECT coalesce(current_setting('app.is_staff', true), 'off') = 'on' $$;
        """
    )

    # ---- narrow lookups that work before the account is visible -------------------
    # SECURITY DEFINER = runs as the table owner (not subject to RLS). Return only what the
    # caller needs; search_path pinned so nobody can shadow the users table.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION rp_user_id_by_sub(p_sub text) RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
        $$ SELECT id FROM users WHERE cognito_sub = p_sub $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION rp_user_by_email(p_email text)
        RETURNS TABLE (id uuid, platform_role varchar)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
        $$ SELECT u.id, u.platform_role FROM users u WHERE u.email = lower(p_email) $$;
        """
    )
    for fn in ("rp_user_id_by_sub(text)", "rp_user_by_email(text)"):
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO {APP_ROLE}")

    # ---- policies ------------------------------------------------------------------
    for table in ("users", "organizations", "clinic_memberships", "clinic_assignments", "notifications"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    op.execute(f"CREATE POLICY users_read ON users FOR SELECT TO {APP_ROLE} USING ({USER_VISIBLE})")
    op.execute(
        f"CREATE POLICY users_update ON users FOR UPDATE TO {APP_ROLE} "
        f"USING ({USER_VISIBLE}) WITH CHECK ({USER_VISIBLE})"
    )
    op.execute(
        f"CREATE POLICY users_insert ON users FOR INSERT TO {APP_ROLE} "
        "WITH CHECK (rp_all_clinics() OR platform_role = 'clinic_user')"
    )

    op.execute(
        f"CREATE POLICY organizations_read ON organizations FOR SELECT TO {APP_ROLE} USING ({ORG_VISIBLE})"
    )
    op.execute(
        f"CREATE POLICY organizations_update ON organizations FOR UPDATE TO {APP_ROLE} "
        f"USING ({ORG_VISIBLE}) WITH CHECK ({ORG_VISIBLE})"
    )
    # Creating a business happens only as the first step of "Add Clinic" (checked by the app).
    op.execute(
        f"CREATE POLICY organizations_insert ON organizations FOR INSERT TO {APP_ROLE} WITH CHECK (true)"
    )

    for table in ("clinic_memberships", "clinic_assignments"):
        op.execute(
            f"CREATE POLICY {table}_read ON {table} FOR SELECT TO {APP_ROLE} USING ({MINE_OR_IN_SCOPE})"
        )
        op.execute(
            f"CREATE POLICY {table}_insert ON {table} FOR INSERT TO {APP_ROLE} WITH CHECK ({IN_SCOPE})"
        )
        op.execute(
            f"CREATE POLICY {table}_update ON {table} FOR UPDATE TO {APP_ROLE} "
            f"USING ({IN_SCOPE}) WITH CHECK ({IN_SCOPE})"
        )

    op.execute(
        f"CREATE POLICY notifications_read ON notifications FOR SELECT TO {APP_ROLE} "
        "USING (rp_all_clinics() OR user_id = rp_user_id())"
    )
    op.execute(
        f"CREATE POLICY notifications_update ON notifications FOR UPDATE TO {APP_ROLE} "
        "USING (rp_all_clinics() OR user_id = rp_user_id()) "
        "WITH CHECK (rp_all_clinics() OR user_id = rp_user_id())"
    )
    op.execute(
        f"CREATE POLICY notifications_insert ON notifications FOR INSERT TO {APP_ROLE} "
        f"WITH CHECK (clinic_id IS NULL OR {IN_SCOPE})"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    policies = {
        "users": ("users_read", "users_update", "users_insert"),
        "organizations": ("organizations_read", "organizations_update", "organizations_insert"),
        "clinic_memberships": (
            "clinic_memberships_read",
            "clinic_memberships_insert",
            "clinic_memberships_update",
        ),
        "clinic_assignments": (
            "clinic_assignments_read",
            "clinic_assignments_insert",
            "clinic_assignments_update",
        ),
        "notifications": ("notifications_read", "notifications_update", "notifications_insert"),
    }
    for table, names in policies.items():
        for name in names:
            op.execute(f"DROP POLICY IF EXISTS {name} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS rp_user_by_email(text)")
    op.execute("DROP FUNCTION IF EXISTS rp_user_id_by_sub(text)")
    op.execute("DROP FUNCTION IF EXISTS rp_is_staff()")
    op.execute("DROP FUNCTION IF EXISTS rp_user_id()")
