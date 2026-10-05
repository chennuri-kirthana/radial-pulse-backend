"""Structured (JSON) logging with request correlation and secret redaction.

Every log line is one JSON object on stdout. In AWS, ECS ships stdout to
CloudWatch Logs, where the fields are queryable with Logs Insights.

Rules (see docs/security/README.md):
* never log tokens, passwords, cookies, full request bodies or presigned URLs
* ``redact()`` masks known-sensitive keys in ``extra={...}`` dicts
* the current request id is attached to every line automatically
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)

SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "password",
        "db_password",
        "secret",
        "client_secret",
        "token",
        "access_token",
        "id_token",
        "refresh_token",
        "api_key",
        "x-api-key",
        "upload_url",
        "download_url",
        "database_url",
    }
)

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def redact(value: Any) -> Any:
    """Recursively replace values of sensitive keys with ``"[REDACTED]"``."""
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if str(k).lower() in SENSITIVE_KEYS else redact(v)) for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str, environment: str, version: str) -> None:
        super().__init__()
        self.static = {"service": service, "env": environment, "version": version}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **self.static,
        }
        if (rid := request_id_ctx.get()) is not None:
            payload["request_id"] = rid
        if (uid := user_id_ctx.get()) is not None:
            payload["user_id"] = uid
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")}
        if extras:
            payload.update(redact(extras))
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str, service: str, environment: str, version: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service=service, environment=environment, version=version))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # uvicorn's access log duplicates our request log and can include query strings; silence it.
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
