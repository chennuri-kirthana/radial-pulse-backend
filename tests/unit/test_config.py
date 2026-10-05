from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

AUTH = {
    "cognito_region": "ap-south-1",
    "cognito_user_pool_id": "ap-south-1_X",
    "cognito_app_client_ids": "a,b",
}


def make(**kw):  # type: ignore[no-untyped-def]
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def test_local_defaults_have_docs_and_no_auth() -> None:
    s = make()
    assert s.app_env == "local"
    assert s.show_docs
    assert not s.auth_configured


def test_csv_env_values_are_split() -> None:
    s = make(**AUTH, cors_allowed_origins="https://a.example.com, https://b.example.com")
    assert s.cognito_app_client_ids == ["a", "b"]
    assert s.cors_allowed_origins == ["https://a.example.com", "https://b.example.com"]
    assert s.cognito_issuer == "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_X"


def test_prod_rules() -> None:
    base = {**AUTH, "app_env": "prod", "db_sslmode": "require"}
    assert not make(**base).show_docs
    with pytest.raises(ValidationError, match="DEBUG"):
        make(**base, debug=True)
    with pytest.raises(ValidationError, match="Wildcard"):
        make(**base, cors_allowed_origins="*")
    with pytest.raises(ValidationError, match="https"):
        make(**base, cors_allowed_origins="http://x.example.com")
    with pytest.raises(ValidationError, match="TLS"):
        make(**{**base, "db_sslmode": "disable"})


def test_dev_requires_auth() -> None:
    with pytest.raises(ValidationError, match="COGNITO"):
        make(app_env="dev")


def test_db_url_from_parts_escapes_password() -> None:
    s = make(db_host="db.internal", db_user="app", db_password="p@ss/w:rd", db_sslmode="require")
    url = s.sqlalchemy_url
    assert url.password == "p@ss/w:rd"
    assert url.query["sslmode"] == "require"
    assert "p@ss" not in repr(url)  # SQLAlchemy masks the password in repr
