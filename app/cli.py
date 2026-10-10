"""Operator commands (run by a person, never by the web app).

    uv run python -m app.cli create-platform-admin --email you@company.com --name "Your Name"

Invite-only sign-in means the FIRST Platform Administrator is created here; after that, admins
invite everyone else through the API. Runs as the database actor ``system`` (rp.actor = 'system'),
so it never needs the owner login. With IDENTITY_DIRECTORY_BACKEND=cognito it also creates the
Cognito account (Cognito emails the temporary password).
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.core.enums import PlatformRole
from app.db.session import get_sessionmaker
from app.db.tenant import act_as_system
from app.integrations.identity_directory import IdentityDirectory
from app.models import User
from app.schemas.common import normalize_email
from app.services import audit


def create_platform_admin(
    email: str,
    name: str | None,
    directory: IdentityDirectory | None = None,
    cognito_sub: str | None = None,
) -> str:
    """Create (or finish linking) the first Platform Administrator.

    ``cognito_sub``: the ``sub`` of a Cognito account that ALREADY exists (made in the console).
    Links the row to it right away and does not call Cognito. For the zero-NAT setup, where neither
    the API nor the migration runner can reach Cognito, this replaces the first-sign-in
    ``/oauth2/userInfo`` link.
    """
    from app.dependencies.adapters import get_identity_directory

    email = normalize_email(email)
    directory = directory or get_identity_directory()
    session = get_sessionmaker()()
    try:
        act_as_system(session)
        existing = session.scalar(select(User).where(User.email == email))
        if existing is not None:
            if existing.platform_role is not PlatformRole.PLATFORM_ADMINISTRATOR:
                raise SystemExit(f"{email} exists with role {existing.platform_role.value}; not changing it.")
            if cognito_sub and existing.cognito_sub not in (None, cognito_sub):
                raise SystemExit(f"{email} is already linked to another Cognito account; not changing it.")
            if existing.cognito_sub is None and cognito_sub:
                existing.cognito_sub = cognito_sub
                audit.record(
                    session,
                    action="user.sign_in_linked",
                    resource_type="user",
                    resource_id=existing.id,
                    clinic_id=None,
                    details={"via": "cli"},
                )
                session.commit()
                return f"{email} is already a Platform Administrator; linked to the Cognito account."
            if existing.cognito_sub is None:  # e.g. the first run could not reach Cognito
                directory.invite(email, existing.full_name)
            return f"{email} is already a Platform Administrator."
        user = User(
            email=email,
            full_name=name,
            platform_role=PlatformRole.PLATFORM_ADMINISTRATOR,
            cognito_sub=cognito_sub,
        )
        session.add(user)
        audit.record(
            session,
            action="user.invited",
            resource_type="user",
            resource_id=user.id,
            clinic_id=None,
            details={
                "platform_role": PlatformRole.PLATFORM_ADMINISTRATOR.value,
                "via": "cli",
                "linked": cognito_sub is not None,
            },
        )
        session.commit()
        if cognito_sub:
            return f"Created Platform Administrator {email}, linked to the existing Cognito account."
        directory.invite(email, name)
        return f"Created Platform Administrator {email}. They sign in with the emailed temporary password."
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-platform-admin", help="Create the first Platform Administrator")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", default=None)
    admin.add_argument(
        "--cognito-sub",
        default=None,
        help="sub of the Cognito account that already exists (console). Links it now; no Cognito call.",
    )
    args = parser.parse_args(argv)
    if args.command == "create-platform-admin":
        print(create_platform_admin(args.email, args.name, cognito_sub=args.cognito_sub))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
