from __future__ import annotations

import json

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


def test_jwks_from_s3_is_optional_and_checked() -> None:
    assert make(**AUTH).cognito_jwks_s3 is None
    assert make(**AUTH, cognito_jwks_s3_uri="").cognito_jwks_s3 is None
    s = make(**AUTH, cognito_jwks_s3_uri="s3://rp-central-jwks-dev-1/cognito/ap-south-1_X/jwks.json")
    assert s.cognito_jwks_s3 == ("rp-central-jwks-dev-1", "cognito/ap-south-1_X/jwks.json")
    assert (
        s.cognito_jwks_url
        == "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_X/.well-known/jwks.json"
    )
    for bad in ("https://bucket/key", "s3://bucket", "s3:///key", "bucket/key"):
        with pytest.raises(ValidationError, match="s3://<bucket>/<key>"):
            make(**AUTH, cognito_jwks_s3_uri=bad)


def test_csv_env_values_are_split() -> None:
    s = make(**AUTH, cors_allowed_origins="https://a.example.com, https://b.example.com")
    assert s.cognito_app_client_ids == ["a", "b"]
    assert s.cors_allowed_origins == ["https://a.example.com", "https://b.example.com"]
    assert s.cognito_issuer == "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_X"


def test_prod_rules() -> None:
    base = {**AUTH, "app_env": "prod", "db_sslmode": "require", "identity_directory_backend": "cognito"}
    assert not make(**base).show_docs
    with pytest.raises(ValidationError, match="DEBUG"):
        make(**base, debug=True)
    with pytest.raises(ValidationError, match="Wildcard"):
        make(**base, cors_allowed_origins="*")
    with pytest.raises(ValidationError, match="https"):
        make(**base, cors_allowed_origins="http://x.example.com")
    with pytest.raises(ValidationError, match="TLS"):
        make(**{**base, "db_sslmode": "disable"})
    with pytest.raises(ValidationError, match="IDENTITY_DIRECTORY_BACKEND"):
        make(**{**base, "identity_directory_backend": "log"})  # invites must create Cognito sign-ins


def test_dev_requires_auth() -> None:
    with pytest.raises(ValidationError, match="COGNITO"):
        make(app_env="dev")


def test_db_url_from_parts_escapes_password() -> None:
    s = make(db_host="db.internal", db_user="app", db_password="p@ss/w:rd", db_sslmode="require")
    url = s.sqlalchemy_url
    assert url.password == "p@ss/w:rd"
    assert url.query["sslmode"] == "require"
    assert "p@ss" not in repr(url)  # SQLAlchemy masks the password in repr


def test_cognito_identity_directory_needs_the_pool() -> None:
    with pytest.raises(ValidationError, match="IDENTITY_DIRECTORY_BACKEND=cognito"):
        make(identity_directory_backend="cognito")
    assert make(**AUTH, identity_directory_backend="cognito").identity_directory_backend == "cognito"


SEO_ROLE = "arn:aws:iam::111122223333:role/seo-backend"
ROLES_JSON = json.dumps({SEO_ROLE: {"name": "seo-agent", "scopes": ["clinics.read"]}})
INTERNAL = {"internal_api_id": "abc123", "internal_trust_lambda_context": True}


def test_service_roles_are_parsed_from_json_and_validated() -> None:
    s = make(**AUTH, **INTERNAL, internal_service_roles=ROLES_JSON)
    assert s.internal_service_roles == {SEO_ROLE: {"name": "seo-agent", "scopes": ["clinics.read"]}}
    assert s.internal_auth_configured
    assert not make(**AUTH).internal_auth_configured


def test_internal_auth_is_off_unless_the_lambda_flag_is_set() -> None:
    s = make(**AUTH, internal_api_id="abc123", internal_service_roles=ROLES_JSON)
    assert not s.internal_trust_lambda_context
    assert not s.internal_auth_configured


def test_trusting_the_lambda_header_off_lambda_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    with pytest.raises(ValidationError, match="only allowed on AWS Lambda"):
        make(**AUTH, app_env="dev", internal_trust_lambda_context=True)
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "central-api")
    assert make(**AUTH, app_env="dev", internal_trust_lambda_context=True).internal_trust_lambda_context


def test_role_with_a_path_is_accepted() -> None:
    arn = "arn:aws:iam::111122223333:role/service-role/seo-backend"
    s = make(**AUTH, **INTERNAL, internal_service_roles={arn: {"name": "seo-agent", "scopes": []}})
    assert list(s.internal_service_roles) == [arn]


def test_service_roles_need_the_api_id_real_arns_and_clean_unique_names() -> None:
    with pytest.raises(ValidationError, match="INTERNAL_API_ID"):
        make(**AUTH, internal_service_roles=ROLES_JSON)
    with pytest.raises(ValidationError, match="must be JSON"):
        make(**AUTH, **INTERNAL, internal_service_roles="seo-agent")
    with pytest.raises(ValidationError, match="not an IAM role ARN"):
        make(**AUTH, **INTERNAL, internal_service_roles={"arn:aws:iam::111122223333:user/x": {"name": "x"}})
    with pytest.raises(ValidationError, match="its own name"):
        make(
            **AUTH,
            **INTERNAL,
            internal_service_roles={
                SEO_ROLE: {"name": "seo-agent", "scopes": []},
                "arn:aws:iam::111122223333:role/other": {"name": "seo-agent", "scopes": []},
            },
        )
    with pytest.raises(ValidationError, match="same role twice"):
        make(
            **AUTH,
            **INTERNAL,
            internal_service_roles={
                SEO_ROLE: {"name": "seo-one", "scopes": []},
                "arn:aws:iam::111122223333:role/team/seo-backend": {"name": "seo-two", "scopes": []},
            },
        )
    with pytest.raises(ValidationError, match="lower-case"):
        make(**AUTH, **INTERNAL, internal_service_roles={SEO_ROLE: {"name": "SEO Agent", "scopes": []}})
    with pytest.raises(ValidationError, match="scopes must be from"):
        make(**AUTH, **INTERNAL, internal_service_roles={SEO_ROLE: {"name": "seo-agent", "scopes": ["all"]}})
