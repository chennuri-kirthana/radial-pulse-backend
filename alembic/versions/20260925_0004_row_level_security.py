"""row-level security + least-privilege application role

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-25

What this does (PostgreSQL only; see docs/architecture/multi-tenancy.md):

1. Creates the NOLOGIN group role ``radial_app``. The API and the worker log in as members
   of it (``radial_api_iam`` / ``radial_worker_iam`` with IAM auth on Aurora; a password
   user locally). Migrations keep running as the table OWNER, which RLS does not restrict.
2. Grants ``radial_app`` plain DML on application tables — and only SELECT/INSERT on
   ``audit_events`` (no UPDATE/DELETE/TRUNCATE: the audit trail cannot be edited by the app).
   ``ALTER DEFAULT PRIVILEGES`` gives the same DML grants on tables future migrations create.
3. Enables row-level security on every clinic-scoped table with one policy:
       rp_all_clinics() OR clinic_id = ANY (rp_clinic_ids())
   where the two helper functions read the transaction-local settings the app sets per
   request (app/db/tenant.py). No settings → no rows (fail closed).

Identity tables (users, organizations, clinic_memberships, clinic_assignments) and
notifications (scoped per recipient) are intentionally NOT under RLS: they are read before
a tenant scope exists (sign-in). The application layer protects them.

Downgrade removes policies, functions and grants but does NOT drop roles (roles are
cluster-wide and may be used by other databases).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "radial_app"
IAM_LOGINS = ("radial_api_iam", "radial_worker_iam")

#: Tables with a NOT NULL clinic_id column.
CLINIC_TABLES = (
    "doctors",
    "clinic_profiles",
    "consent_records",
    "assets",
    "approvals",
    "work_items",
    "metric_snapshots",
    "report_artifacts",
    "assessments",
    "assessment_components",
    "assessment_findings",
    "presence_profiles",
    "background_jobs",
)

TENANT_PREDICATE = "rp_all_clinics() OR clinic_id = ANY (rp_clinic_ids())"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    # 1. roles ------------------------------------------------------------------
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            CREATE ROLE {APP_ROLE} NOLOGIN;
          END IF;
        END $$;
        """
    )
    # IAM-authenticated logins exist only on RDS/Aurora (the rds_iam role is present there).
    for login in IAM_LOGINS:
        op.execute(
            f"""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rds_iam')
                 AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{login}') THEN
                CREATE ROLE {login} LOGIN IN ROLE {APP_ROLE};
                GRANT rds_iam TO {login};
              END IF;
            END $$;
            """
        )

    # 2. privileges ------------------------------------------------------------
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"REVOKE ALL ON alembic_version FROM {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM {APP_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )

    # 3. tenant context helpers --------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION rp_all_clinics() RETURNS boolean
        LANGUAGE sql STABLE AS
        $$ SELECT coalesce(current_setting('app.all_clinics', true), 'off') = 'on' $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION rp_clinic_ids() RETURNS uuid[]
        LANGUAGE sql STABLE AS
        $$ SELECT coalesce(nullif(current_setting('app.clinic_ids', true), ''), '{}')::uuid[] $$;
        """
    )

    # 4. policies ------------------------------------------------------------------
    op.execute("ALTER TABLE clinics ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON clinics TO {APP_ROLE} "
        "USING (rp_all_clinics() OR id = ANY (rp_clinic_ids())) "
        "WITH CHECK (rp_all_clinics() OR id = ANY (rp_clinic_ids()))"
    )
    for table in CLINIC_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} TO {APP_ROLE} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )
    # audit_events: clinic events follow the tenant rule; platform events (clinic_id NULL)
    # may be written by anyone but read only with the all-clinics scope.
    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY audit_read ON audit_events FOR SELECT TO {APP_ROLE} USING ({TENANT_PREDICATE})"
    )
    op.execute(
        f"CREATE POLICY audit_write ON audit_events FOR INSERT TO {APP_ROLE} "
        f"WITH CHECK (clinic_id IS NULL OR {TENANT_PREDICATE})"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP POLICY IF EXISTS audit_read ON audit_events")
    op.execute("DROP POLICY IF EXISTS audit_write ON audit_events")
    op.execute("ALTER TABLE audit_events DISABLE ROW LEVEL SECURITY")
    for table in ("clinics", *CLINIC_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS rp_clinic_ids()")
    op.execute("DROP FUNCTION IF EXISTS rp_all_clinics()")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
