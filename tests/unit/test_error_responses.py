"""The Problem JSON body (CLAUDE.md): type, title, status, code, detail, request_id (+ fields for 400)."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.core.error_handlers import register_error_handlers
from app.core.errors import AccountDisabledError, ConflictError, InvalidRequestError
from app.middleware.request_context import RequestContextMiddleware


class FakeDriverError(Exception):
    """Looks like a psycopg error: sqlstate + diag."""

    def __init__(self, sqlstate: str, **diag: str) -> None:
        super().__init__("raw database text that must never reach the user")
        self.sqlstate = sqlstate
        self.diag = SimpleNamespace(
            message_primary=None, constraint_name=None, table_name=None, column_name=None
        )
        for key, value in diag.items():
            setattr(self.diag, key, value)


class Body(BaseModel):
    consultation_fee: float = Field(ge=0)


def make_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    @app.post("/validate")
    def validate(body: Body) -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/raise/{kind}")
    def raise_it(kind: str) -> None:
        if kind == "disabled":
            raise AccountDisabledError("This account is disabled.")
        if kind == "conflict":
            raise ConflictError("Already done.")
        if kind == "invalid":
            raise InvalidRequestError("Bad fee.", fields={"consultation_fee": "Must be 0 or more."})
        if kind == "db-unique":
            raise IntegrityError("INSERT …", {}, FakeDriverError("23505", constraint_name="uq_users_email"))
        if kind == "db-guard":
            raise ProgrammingError(
                "UPDATE …", {}, FakeDriverError("42501", message_primary="only staff can do this")
            )
        if kind == "db-other":
            raise ProgrammingError("SELECT …", {}, FakeDriverError("22012"))

    return TestClient(app, raise_server_exceptions=False)


def test_validation_error_is_400_invalid_request_with_fields() -> None:
    r = make_client().post("/validate", json={"consultation_fee": -5})
    body = r.json()
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    assert (body["code"], body["type"], body["status"]) == ("invalid_request", "invalid_request", 400)
    assert list(body["fields"]) == ["consultation_fee"]
    assert "-5" not in r.text  # the input is never echoed
    assert body["request_id"] == r.headers["x-request-id"]


def test_app_errors_keep_their_code() -> None:
    client = make_client()
    assert client.get("/raise/disabled").json()["code"] == "account_disabled"
    assert client.get("/raise/disabled").status_code == 403
    conflict = client.get("/raise/conflict")
    assert (conflict.status_code, conflict.json()["code"]) == (409, "state_conflict")
    invalid = client.get("/raise/invalid").json()
    assert (invalid["status"], invalid["fields"]) == (400, {"consultation_fee": "Must be 0 or more."})


def test_database_refusals_are_mapped_and_never_leak_raw_text() -> None:
    client = make_client()
    unique = client.get("/raise/db-unique")
    assert (unique.status_code, unique.json()["code"]) == (409, "state_conflict")
    guard = client.get("/raise/db-guard")
    assert (guard.status_code, guard.json()["code"], guard.json()["detail"]) == (
        403,
        "forbidden",
        "only staff can do this",
    )
    other = client.get("/raise/db-other")
    assert (other.status_code, other.json()["code"]) == (500, "internal_error")
    for r in (unique, guard, other):
        assert "raw database text" not in r.text
        assert "fields" not in r.json()
