"""`python -m app.cli create-platform-admin`, including the zero-NAT `--cognito-sub` link."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import app.cli as cli
from app.core.enums import PlatformRole
from app.models import AuditEvent, User
from tests.conftest import FakeIdentityDirectory


@pytest.fixture
def directory(
    monkeypatch: pytest.MonkeyPatch, session_factory: sessionmaker[Session]
) -> FakeIdentityDirectory:
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: session_factory)
    return FakeIdentityDirectory()


def test_create_with_invite_calls_cognito(directory: FakeIdentityDirectory, db: Session) -> None:
    message = cli.create_platform_admin("Admin@Example.test", "Ada", directory)
    assert "sign in with the emailed temporary password" in message
    user = db.scalar(select(User).where(User.email == "admin@example.test"))
    assert user is not None and user.platform_role is PlatformRole.PLATFORM_ADMINISTRATOR
    assert [c.email for c in directory.sent] == ["admin@example.test"]  # Cognito was asked to invite


def test_create_with_cognito_sub_links_now_and_never_calls_cognito(
    directory: FakeIdentityDirectory, db: Session
) -> None:
    message = cli.create_platform_admin("admin@example.test", None, directory, cognito_sub="7a1f-real-sub")
    assert "linked to the existing Cognito account" in message
    user = db.scalar(select(User).where(User.email == "admin@example.test"))
    assert user is not None and user.cognito_sub == "7a1f-real-sub"
    assert directory.sent == []  # no Cognito call: works without internet
    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "user.invited")).all()
    assert [e.details.get("linked") for e in events] == [True]


def test_existing_unlinked_admin_gets_linked(directory: FakeIdentityDirectory, db: Session) -> None:
    cli.create_platform_admin("admin@example.test", None, directory)
    message = cli.create_platform_admin("admin@example.test", None, directory, cognito_sub="7a1f-real-sub")
    assert "linked to the Cognito account" in message
    user = db.scalar(select(User).where(User.email == "admin@example.test"))
    assert user is not None and user.cognito_sub == "7a1f-real-sub"
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "user.sign_in_linked")) is not None
    # Linked already: a different sub is refused, the same sub is a no-op.
    with pytest.raises(SystemExit, match="already linked to another Cognito account"):
        cli.create_platform_admin("admin@example.test", None, directory, cognito_sub="other-sub")
    again = cli.create_platform_admin("admin@example.test", None, directory, cognito_sub="7a1f-real-sub")
    assert again == "admin@example.test is already a Platform Administrator."


def test_command_line_passes_the_sub(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}

    def fake(email: str, name: str | None, directory: object = None, cognito_sub: str | None = None) -> str:
        seen.update(email=email, name=name, cognito_sub=cognito_sub)
        return "ok"

    monkeypatch.setattr(cli, "create_platform_admin", fake)
    assert cli.main(["create-platform-admin", "--email", "a@b.test", "--cognito-sub", "s-1"]) == 0
    assert seen == {"email": "a@b.test", "name": None, "cognito_sub": "s-1"}
    assert capsys.readouterr().out.strip() == "ok"
