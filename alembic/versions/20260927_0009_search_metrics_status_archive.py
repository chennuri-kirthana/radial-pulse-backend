"""fast search, metric numbers, report status kept in step, audit archiving

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-27

In plain words:

1. Fast search (#6). pg_trgm "trigram" indexes so ``ILIKE '%smile%'`` stays fast with many
   clinics: clinics.name, clinics.website_url, practitioners.full_name, users.email,
   users.full_name.
2. Metric numbers (#4). metric_snapshots.value_number holds the plain number of a metric
   ({"value": 5432} → 5432) so charts can use SQL. Existing rows are back-filled.
3. One report status (#7). The approvals table owns the review status; assessments,
   report_artifacts and assets keep a copy for fast filtering. The database now REFUSES to
   commit a transaction that leaves the copy different from its approval row (checked at
   commit time, so the order of the updates inside the transaction does not matter).
4. Audit archiving (#3). audit_events stays append-only, EXCEPT for the archive job: it may
   delete rows it has already copied to S3, only when it sets ``app.archiving = on`` in its
   transaction. The app role still has no DELETE privilege on audit_events at all, so only the
   owner login (used by the archive task) can do this.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGRAM_INDEXES = [  # (name, table, column)
    ("ix_clinics_name_trgm", "clinics", "name"),
    ("ix_clinics_website_url_trgm", "clinics", "website_url"),
    ("ix_practitioners_full_name_trgm", "practitioners", "full_name"),
    ("ix_users_email_trgm", "users", "email"),
    ("ix_users_full_name_trgm", "users", "full_name"),
]

#: resource table -> does it carry publication_state too?
STATUS_COPIES = {
    "assessment": ("assessments", True),
    "report_artifact": ("report_artifacts", True),
    "asset": ("assets", False),
}


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # ---- 4. metric numbers ---------------------------------------------------------
    op.add_column("metric_snapshots", sa.Column("value_number", sa.Numeric(20, 6), nullable=True))
    if not _is_postgres():
        return
    # Only plain JSON numbers that fit NUMERIC(20, 6) are copied.
    op.execute(
        """
        UPDATE metric_snapshots
        SET value_number = (value ->> 'value')::numeric
        WHERE jsonb_typeof(value -> 'value') = 'number'
          AND abs((value ->> 'value')::numeric) < 1e14
        """
    )

    # ---- 6. fast search ---------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, column in TRIGRAM_INDEXES:
        op.execute(f"CREATE INDEX {name} ON {table} USING gin ({column} gin_trgm_ops)")

    # ---- 7. the report status copy can never drift from its approval ---------------------
    # Deferred constraint triggers run at COMMIT, but NEW is the row as it was at the event
    # (e.g. an approval INSERTed as 'draft' and then UPDATEd to 'submitted' in the same
    # transaction). So each check re-reads the CURRENT rows by id instead of trusting NEW.
    # SECURITY DEFINER: the check must see the rows regardless of row-level security.
    branches = []
    for resource_type, (table, has_pub) in STATUS_COPIES.items():
        pub = " OR r.publication_state IS DISTINCT FROM a.publication_state" if has_pub else ""
        branches.append(
            f"IF EXISTS (SELECT 1 FROM approvals a JOIN {table} r ON r.id = a.resource_id "
            f"WHERE a.id = NEW.id AND a.resource_type = '{resource_type}' "
            f"AND (r.approval_state IS DISTINCT FROM a.state{pub})) THEN "
            f"RAISE EXCEPTION 'review status of % % is out of step with its approval', "
            f"NEW.resource_type, NEW.resource_id USING ERRCODE = 'check_violation'; END IF;"
        )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION rp_check_approval_copy() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        BEGIN
          {" ".join(branches)}
          RETURN NULL;
        END $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER approvals_copy_in_step
        AFTER INSERT OR UPDATE ON approvals
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION rp_check_approval_copy()
        """
    )
    for resource_type, (table, has_pub) in STATUS_COPIES.items():
        pub = " OR r.publication_state IS DISTINCT FROM a.publication_state" if has_pub else ""
        columns = "approval_state, publication_state" if has_pub else "approval_state"
        op.execute(
            f"""
            CREATE OR REPLACE FUNCTION rp_check_{table}_status() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
            BEGIN
              -- No approval row yet: the resource keeps its own starting status.
              IF EXISTS (SELECT 1 FROM approvals a JOIN {table} r ON r.id = a.resource_id
                         WHERE r.id = NEW.id AND a.resource_type = '{resource_type}'
                           AND (r.approval_state IS DISTINCT FROM a.state{pub})) THEN
                RAISE EXCEPTION 'review status of {resource_type} % must change through approvals', NEW.id
                  USING ERRCODE = 'check_violation';
              END IF;
              RETURN NULL;
            END $$;
            """
        )
        op.execute(
            f"""
            CREATE CONSTRAINT TRIGGER {table}_status_in_step
            AFTER UPDATE OF {columns} ON {table}
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION rp_check_{table}_status()
            """
        )

    # ---- 3. audit archiving: allow deletes ONLY for the archive job ----------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_events_block_mutation() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND coalesce(current_setting('app.archiving', true), 'off') = 'on' THEN
            RETURN OLD;  -- the archive job, after copying the rows to S3
          END IF;
          RAISE EXCEPTION 'audit_events is append-only (% blocked)', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    if _is_postgres():
        op.execute(
            """
            CREATE OR REPLACE FUNCTION audit_events_block_mutation() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'audit_events is append-only (% blocked)', TG_OP;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        for _, (table, _) in STATUS_COPIES.items():
            op.execute(f"DROP TRIGGER IF EXISTS {table}_status_in_step ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS rp_check_{table}_status()")
        op.execute("DROP TRIGGER IF EXISTS approvals_copy_in_step ON approvals")
        op.execute("DROP FUNCTION IF EXISTS rp_check_approval_copy()")
        for name, _, _ in TRIGRAM_INDEXES:
            op.execute(f"DROP INDEX IF EXISTS {name}")
        # pg_trgm is left installed (harmless; other objects may use it).
    op.drop_column("metric_snapshots", "value_number")
