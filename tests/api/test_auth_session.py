"""Steps C2 + C3: the database session per request, and sign-in (CLAUDE.md rules 4, 5, 6)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import ClinicMemberRole, PlatformRole
from app.db.tenant import act_as_service, act_as_system, act_as_user
from app.integrations.cognito import UserInfo
from app.models import AuditEvent, Clinic, User
from app.services.identity import build_principal
from tests.conftest import FakeUserInfo, new_sub
from tests.factories import World, build_world, make_user

pytestmark = pytest.mark.integration

APP_DIR = Path(__file__).resolve().parents[2] / "app"


@pytest.fixture
def world(db: Session) -> World:
    return build_world(db)


# ------------------------------------------------------------------ sign-in (rule 6)
@pytest.mark.parametrize(
    ("who", "role"),
    [
        ("admin", PlatformRole.PLATFORM_ADMINISTRATOR),
        ("dsm", PlatformRole.DIGITAL_SUCCESS_MANAGER),
        ("clinic_admin", PlatformRole.CLINIC_MEMBER),
        ("team_member", PlatformRole.CLINIC_MEMBER),
        ("practitioner", PlatformRole.PRACTITIONER),
    ],
)
def test_me_for_every_role(client: TestClient, auth, world: World, who: str, role: PlatformRole) -> None:  # type: ignore[no-untyped-def]
    user = world.people_a()[who]
    r = client.get("/api/v1/auth/me", headers=auth(user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["id"], body["platform_role"]) == (str(user.id), role.value)
    if who == "admin":
        assert body["all_clinics"] is True and body["clinics"] == []
        assert "client_organizations:manage" in body["permissions"]
    else:
        assert [c["clinic_id"] for c in body["clinics"]] == [str(world.clinic_a.id)]
        assert body["permissions"] == []
    if who == "practitioner":
        assert body["practitioner_id"] == str(world.practitioner_a.id)
        assert body["clinics"][0]["is_practitioner"] is True
    if who == "team_member":
        assert body["clinics"][0]["clinic_member_role"] == "clinic_team_member"
        assert "voice_samples:read" not in body["clinics"][0]["permissions"]


def test_switched_off_account_is_403_account_disabled(client: TestClient, auth, db: Session) -> None:  # type: ignore[no-untyped-def]
    user = make_user(db, PlatformRole.PLATFORM_ADMINISTRATOR, active=False)
    db.commit()
    r = client.get("/api/v1/auth/me", headers=auth(user))
    assert (r.status_code, r.json()["code"]) == (403, "account_disabled")


def test_unknown_sign_in_is_403_account_disabled(client: TestClient, make_token) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {make_token(new_sub())}"})
    assert (r.status_code, r.json()["code"]) == (403, "account_disabled")


def test_first_sign_in_links_the_invited_account(
    client: TestClient, make_token, db: Session, userinfo: FakeUserInfo
) -> None:  # type: ignore[no-untyped-def]
    invited = make_user(db, PlatformRole.PLATFORM_ADMINISTRATOR, "new.admin@example.test", linked=False)
    db.commit()
    sub = new_sub()
    userinfo.by_token_sub[sub] = UserInfo(email="New.Admin@Example.test", email_verified=True, name=None)
    header = {"Authorization": f"Bearer {make_token(sub)}"}

    assert client.get("/api/v1/auth/me", headers=header).status_code == 200
    db.expire_all()
    assert db.get(User, invited.id).cognito_sub == sub  # type: ignore[union-attr]
    linked = db.scalars(select(AuditEvent).where(AuditEvent.action == "user.sign_in_linked")).all()
    assert [(e.actor_user_id, e.actor_type) for e in linked] == [(invited.id, "user")]

    userinfo.by_token_sub.clear()  # the second time, the sub alone is enough
    assert client.get("/api/v1/auth/me", headers=header).status_code == 200


def test_unverified_email_never_links(
    client: TestClient, make_token, db: Session, userinfo: FakeUserInfo
) -> None:  # type: ignore[no-untyped-def]
    make_user(db, PlatformRole.PLATFORM_ADMINISTRATOR, "someone@example.test", linked=False)
    db.commit()
    sub = new_sub()
    userinfo.by_token_sub[sub] = UserInfo(email="someone@example.test", email_verified=False, name=None)
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {make_token(sub)}"})
    assert (r.status_code, r.json()["code"]) == (403, "account_disabled")


def test_missing_or_wrong_tokens_are_401(client: TestClient, make_token, world: World) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/v1/auth/me").status_code == 401
    id_token = make_token(world.admin.cognito_sub, token_use="id")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {id_token}"}).status_code == 401
    expired = make_token(world.admin.cognito_sub, exp=1, iat=0)
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_a_role_only_counts_with_its_own_link(db: Session, session_factory: sessionmaker[Session]) -> None:
    """A clinic_member login with a portfolio allocation by mistake is still NOT a DSM."""
    world = build_world(db)
    session = session_factory()
    act_as_user(session, world.clinic_admin_a.id)
    principal = build_principal(session, session.get(User, world.clinic_admin_a.id))  # type: ignore[arg-type]
    assert principal.dsm_clinic_ids == frozenset()
    assert principal.clinic_roles == {world.clinic_a.id: ClinicMemberRole.CLINIC_ADMINISTRATOR}
    session.close()


# ------------------------------------------------------------------ the session (rules 4 + 5)
def _visible_clinics(session_factory: sessionmaker[Session], user: User | None) -> set[str]:
    session = session_factory()
    if user is not None:
        act_as_user(session, user.id)
    names = set(session.scalars(select(Clinic.name)))
    session.close()
    return names


def test_each_role_sees_only_its_clinics(db: Session, session_factory: sessionmaker[Session]) -> None:
    w = build_world(db)
    both = {"Family Dental Clinic", "SmileCare Andheri"}
    assert _visible_clinics(session_factory, w.admin) == both
    assert _visible_clinics(session_factory, w.dsm_a) == {"Family Dental Clinic"}
    assert _visible_clinics(session_factory, w.clinic_admin_a) == {"Family Dental Clinic"}
    assert _visible_clinics(session_factory, w.practitioner_login_a) == {"Family Dental Clinic"}
    assert _visible_clinics(session_factory, w.clinic_admin_b) == {"SmileCare Andheri"}
    assert _visible_clinics(session_factory, None) == set()  # nobody signed in: nothing (fail closed)


def test_system_and_service_actors(db: Session, session_factory: sessionmaker[Session]) -> None:
    build_world(db)
    session = session_factory()
    act_as_system(session)
    assert len(session.scalars(select(Clinic.id)).all()) == 2
    session.commit()
    act_as_service(session)
    assert session.scalar(text("SELECT current_user")) == "radial_service"
    assert len(session.scalars(select(Clinic.id)).all()) == 2  # read-only role sees clinics
    session.close()


def test_pooled_connection_never_keeps_the_previous_user(engine: Engine, db: Session) -> None:
    """Two requests on the SAME pooled connection: the second never sees the first one's identity."""
    w = build_world(db)
    one_connection = create_engine(engine.url, pool_size=1, max_overflow=0)
    factory = sessionmaker(bind=one_connection)
    first = factory()
    act_as_user(first, w.admin.id)
    assert first.scalar(text("SELECT current_setting('rp.user_id', true)")) == str(w.admin.id)
    assert first.scalar(text("SELECT current_user")) == "radial_app"
    first.commit()
    first.close()

    with one_connection.connect() as raw:  # same physical connection, no actor hook
        assert raw.scalar(text("SELECT coalesce(current_setting('rp.user_id', true), '')")) == ""
        assert raw.scalar(text("SELECT current_user")) == "radial_app_test"  # SET LOCAL ROLE ended too
    second = factory()
    assert second.scalars(select(Clinic.id)).all() == []  # a new request with no user sees nothing
    second.close()
    one_connection.dispose()


def test_the_app_login_owns_no_tables(engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM pg_tables WHERE tableowner = current_user")) == 0


def test_code_never_uses_plain_set() -> None:
    """Only SET LOCAL / set_config(..., true): a plain SET would stay on the pooled connection."""
    # SQL in this code base is upper-case; the English word "Set" in docs is not matched.
    # (ondelete="SET NULL" on foreign keys is not a session setting)
    plain_set = re.compile(r"""["']\s*SET\s+(?!LOCAL\b|NULL\b|DEFAULT\b)\w""")
    session_false = re.compile(r"set_config\([^)]*,\s*false\s*\)", re.IGNORECASE)
    offenders = [
        f"{path.relative_to(APP_DIR)}:{n}"
        for path in APP_DIR.rglob("*.py")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if plain_set.search(line) or session_false.search(line)
    ]
    assert offenders == []
