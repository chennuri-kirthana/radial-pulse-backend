"""Engine and session management.

One engine per process (connection pool). One session per request, opened by the
``get_db`` dependency and always closed. Services decide when to commit.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db import tenant as _tenant  # noqa: F401  (registers the RLS after_begin hook)


def build_engine(settings: Settings) -> Engine:
    url = settings.sqlalchemy_url
    kwargs: dict[str, object] = {"echo": settings.db_echo, "pool_pre_ping": True, "future": True}
    if url.get_backend_name() == "postgresql":
        kwargs.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_recycle=settings.db_pool_recycle_seconds,
            connect_args={"application_name": settings.service_name, "connect_timeout": 5},
        )
    engine = create_engine(url, **kwargs)
    if settings.db_iam_auth:
        _use_iam_auth(engine, settings)
    return engine


def _use_iam_auth(engine: Engine, settings: Settings) -> None:
    """Aurora IAM authentication: a fresh 15-minute token for every NEW pooled connection.

    The ECS task role grants `rds-db:connect` for exactly this DB user. No password exists.
    """
    import boto3

    rds = boto3.client("rds", region_name=settings.aws_region)

    @event.listens_for(engine, "do_connect")
    def _token(dialect: object, conn_rec: object, cargs: object, cparams: dict[str, object]) -> None:
        cparams["password"] = rds.generate_db_auth_token(
            DBHostname=settings.db_host,
            Port=settings.db_port,
            DBUsername=settings.db_user,
            Region=settings.aws_region,
        )


@lru_cache
def get_engine() -> Engine:
    return build_engine(get_settings())


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def session_scope() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
