from __future__ import annotations

import json
import logging

from app.core.logging import JsonFormatter, redact, request_id_ctx


def test_redact_masks_nested_sensitive_keys() -> None:
    data = {"Authorization": "Bearer x", "nested": {"password": "p", "ok": 1}, "items": [{"token": "t"}]}
    assert redact(data) == {
        "Authorization": "[REDACTED]",
        "nested": {"password": "[REDACTED]", "ok": 1},
        "items": [{"token": "[REDACTED]"}],
    }


def test_json_formatter_includes_request_id_and_redacts_extras() -> None:
    formatter = JsonFormatter(service="api", environment="test", version="1")
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", (), None)
    record.upload_url = "https://secret"  # type: ignore[attr-defined]
    record.status = 200  # type: ignore[attr-defined]
    token = request_id_ctx.set("req-123")
    try:
        line = json.loads(formatter.format(record))
    finally:
        request_id_ctx.reset(token)
    assert line["request_id"] == "req-123"
    assert line["upload_url"] == "[REDACTED]"
    assert line["status"] == 200
    assert line["service"] == "api"
