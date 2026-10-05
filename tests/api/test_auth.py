from __future__ import annotations

from app.core.enums import PlatformRole
from app.integrations.cognito import UserInfo
from app.models import AuditEvent, User
from tests.conftest import new_sub
from tests.factories import make_user


def test_missing_token_is_401_problem_json(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["type"] == "unauthorized"
    assert body["request_id"] == r.headers["x-request-id"]
    assert r.headers["www-authenticate"] == "Bearer"


def test_invalid_token_is_401(client, make_token) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {make_token('x', token_use='id')}"})
    assert r.status_code == 401


def test_me_for_linked_admin(client, db, auth) -> None:  # type: ignore[no-untyped-def]
    admin = make_user(db, PlatformRole.PLATFORM_ADMINISTRATOR)
    r = client.get("/api/v1/auth/me", headers=auth(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["platform_role"] == "platform_administrator"
    assert body["all_clinics"] is True
    assert "users:manage" in body["permissions"]


def test_first_sign_in_links_preprovisioned_user(client, db, make_token, userinfo) -> None:  # type: ignore[no-untyped-def]
    user = make_user(db, PlatformRole.DIGITAL_SUCCESS_MANAGER, email="new.dsm@example.test", linked=False)
    sub = new_sub()
    userinfo.by_token_sub[sub] = UserInfo(email="New.DSM@example.test", email_verified=True, name="New A")
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {make_token(sub)}"})
    assert r.status_code == 200, r.text
    db.expire_all()
    linked = db.get(User, user.id)
    assert linked.cognito_sub == sub
    assert linked.full_name == "New A"
    assert db.query(AuditEvent).filter_by(action="user.identity_linked").count() == 1


def test_unknown_or_unverified_email_is_refused(client, make_token, userinfo) -> None:  # type: ignore[no-untyped-def]
    stranger = new_sub()
    userinfo.by_token_sub[stranger] = UserInfo(email="nobody@example.test", email_verified=True, name=None)
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {make_token(stranger)}"})
    assert r.status_code == 403
    assert r.json()["type"] == "not_provisioned"

    unverified = new_sub()
    userinfo.by_token_sub[unverified] = UserInfo(email="x@example.test", email_verified=False, name=None)
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {make_token(unverified)}"})
    assert r.status_code == 403


def test_email_already_linked_to_other_identity_is_refused(client, db, make_token, userinfo) -> None:  # type: ignore[no-untyped-def]
    make_user(db, PlatformRole.CLINIC_USER, email="taken@example.test", linked=True)
    attacker = new_sub()
    userinfo.by_token_sub[attacker] = UserInfo(email="taken@example.test", email_verified=True, name=None)
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {make_token(attacker)}"})
    assert r.status_code == 403


def test_disabled_user_is_refused(client, db, auth) -> None:  # type: ignore[no-untyped-def]
    user = make_user(db, PlatformRole.CLINIC_USER)
    user.is_active = False
    db.commit()
    assert client.get("/api/v1/auth/me", headers=auth(user)).status_code == 403
