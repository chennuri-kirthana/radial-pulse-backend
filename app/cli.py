"""Operator commands (run by a human, never by the web app).

    uv run python -m app.cli create-platform-admin --email you@company.com --name "Your Name"
    uv run python -m app.cli seed-demo      # demo clinics like the screen designs (never in prod)
    uv run python -m app.cli archive-old-data [--dry-run]   # old metrics/audit rows → S3 archive
    uv run python -m app.cli cleanup-stale-uploads [--dry-run]   # uploads never confirmed → removed

Invite-only sign-in means the FIRST Platform Administrator must be created from the command
line (after that, admins invite everyone else through the API). In AWS, run it as a
one-off ECS task with the same image, like migrations.
"""

from __future__ import annotations

import argparse
import sys

from app.core.config import get_settings
from app.core.enums import PlatformRole
from app.db.session import get_sessionmaker
from app.db.tenant import set_tenant_scope
from app.integrations.storage import ObjectStorage
from app.models import User
from app.repositories.users import UserRepository
from app.schemas.common import normalize_email
from app.services import audit


def create_platform_admin(email: str, name: str | None) -> str:
    email = normalize_email(email)
    session = get_sessionmaker()()
    try:
        set_tenant_scope(session, None)  # operator command: sees every account (row-level security)
        repo = UserRepository(session)
        existing = repo.get_by_email(email)
        if existing is not None:
            if existing.platform_role is not PlatformRole.PLATFORM_ADMINISTRATOR:
                raise SystemExit(f"{email} exists with role {existing.platform_role.value}; not changing it.")
            return f"{email} is already a Platform Administrator."
        user = User(email=email, full_name=name, platform_role=PlatformRole.PLATFORM_ADMINISTRATOR)
        repo.add(user)
        audit.record(
            session,
            actor=None,
            action="user.create",
            resource_type="user",
            resource_id=user.id,
            clinic_id=None,
            details={"platform_role": "platform_administrator", "via": "cli"},
        )
        session.commit()
        return f"Created Platform Administrator {email}. They can now sign in with Google."
    finally:
        session.close()


def seed_demo() -> str:
    from app.seed import seed_demo as _seed

    if get_settings().app_env == "prod":
        raise SystemExit("Refusing to add demo data in prod.")
    session = get_sessionmaker()()
    try:
        return _seed(session)
    finally:
        session.close()


def archive_old_data(dry_run: bool, metrics_days: int | None, audit_days: int | None) -> str:
    """Move old metric snapshots and audit events to the S3 archive (see services/archiving.py).

    Runs with the database OWNER login (MIGRATION_DATABASE_URL / DB master secret), like the
    migrate task — never as the app role.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from app.integrations.archive import ArchiveStore, LocalArchiveStore, S3ArchiveStore
    from app.services.archiving import archive_old_data as _archive

    settings = get_settings()
    if metrics_days is not None and metrics_days < 30:
        raise SystemExit("--metrics-days must be at least 30")
    if audit_days is not None and audit_days < 90:
        raise SystemExit("--audit-days must be at least 90")
    store: ArchiveStore
    if settings.archive_bucket:
        store = S3ArchiveStore(settings.archive_bucket, settings.aws_region, settings.s3_kms_key_id)
        where = f"s3://{settings.archive_bucket}"
    else:
        if settings.app_env in ("dev", "prod"):
            raise SystemExit("ARCHIVE_BUCKET is not set; refusing to archive to a local folder in AWS.")
        store = LocalArchiveStore(settings.archive_local_dir)
        where = settings.archive_local_dir
    engine = create_engine(settings.sqlalchemy_migration_url)
    session = sessionmaker(bind=engine)()
    if engine.dialect.name == "postgresql":
        # The app login cannot see (row-level security) or delete these rows: it would silently
        # "move 0 rows". Insist on the owner login (MIGRATION_DATABASE_URL / the DB master secret).
        owner = session.scalar(text("SELECT tableowner FROM pg_tables WHERE tablename = 'audit_events'"))
        if owner != session.scalar(text("SELECT current_user")):
            session.close()
            engine.dispose()
            raise SystemExit("archive-old-data must run with the database OWNER login (like migrations).")
    try:
        results = _archive(
            session,
            store,
            prefix=settings.app_env,
            metrics_after_days=metrics_days or settings.archive_metrics_after_days,
            audit_after_days=audit_days or settings.archive_audit_after_days,
            dry_run=dry_run,
        )
    finally:
        session.close()
        engine.dispose()
    verb = "would move" if dry_run else "moved"
    lines = [
        f"{r.table}: {verb} {r.rows} rows older than {r.cutoff:%Y-%m-%d} ({len(r.files)} files)"
        for r in results
    ]
    return "\n".join([*lines, f"archive: {where}"])


def cleanup_stale_uploads(dry_run: bool, hours: int | None, storage: ObjectStorage | None = None) -> str:
    """Remove uploads that were never confirmed: the S3 object (if any) goes, the row becomes FAILED.

    Run it on a schedule (e.g. daily) with the APP login: it uses the all-clinics scope, never the
    owner login. DevOps should ALSO add an S3 lifecycle rule as a second net.
    """
    from datetime import timedelta

    from app.db.base import utcnow
    from app.dependencies.adapters import get_storage
    from app.services.assets import expire_stale_uploads

    settings = get_settings()
    hours = hours if hours is not None else settings.stale_upload_hours
    if hours < 1:
        raise SystemExit("--hours must be at least 1")
    store = storage or get_storage()
    cutoff = utcnow() - timedelta(hours=hours)
    session = get_sessionmaker()()
    total = 0
    try:
        set_tenant_scope(session, None)  # operator command: every clinic
        while True:
            count = expire_stale_uploads(session, store, cutoff, dry_run=dry_run)
            total += count
            if dry_run or count == 0:
                break
    finally:
        session.close()
    verb = "would remove" if dry_run else "removed"
    return f"{verb} {total} uploads not confirmed within {hours} hours"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-platform-admin", help="Create the first Platform Administrator")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", default=None)
    sub.add_parser("seed-demo", help="Add demo clinics and people (local/dev only)")
    archive = sub.add_parser("archive-old-data", help="Move old metrics and audit rows to the S3 archive")
    archive.add_argument("--dry-run", action="store_true", help="Only count what would move")
    archive.add_argument("--metrics-days", type=int, default=None, help="Keep this many days of metrics")
    archive.add_argument("--audit-days", type=int, default=None, help="Keep this many days of audit log")
    cleanup = sub.add_parser("cleanup-stale-uploads", help="Remove uploads that were never confirmed")
    cleanup.add_argument("--dry-run", action="store_true", help="Only count what would be removed")
    cleanup.add_argument("--hours", type=int, default=None, help="Older than this many hours (default 24)")
    args = parser.parse_args(argv)
    if args.command == "create-platform-admin":
        sys.stdout.write(create_platform_admin(args.email, args.name) + "\n")
    elif args.command == "seed-demo":
        sys.stdout.write(seed_demo() + "\n")
    elif args.command == "archive-old-data":
        sys.stdout.write(archive_old_data(args.dry_run, args.metrics_days, args.audit_days) + "\n")
    elif args.command == "cleanup-stale-uploads":
        sys.stdout.write(cleanup_stale_uploads(args.dry_run, args.hours) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
