"""Request id + access log middleware (pure ASGI, no body buffering).

* Accepts an incoming ``X-Request-ID`` (e.g. from API Gateway) if it looks safe,
  otherwise generates one. Echoes it on the response.
* Stores it in a contextvar so every log line and error body carries it.
* Logs one structured line per request: method, path, route template, status, duration.
  Query strings are NOT logged (they can carry personal data or signed URLs).
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_ctx, user_id_ctx

logger = logging.getLogger("app.access")

HEADER = b"x-request-id"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(HEADER, b"").decode("latin-1")
        request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        request_id_ctx.set(request_id)
        user_id_ctx.set(None)
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((HEADER, request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            logger.info(
                "request",
                extra={
                    "http_method": scope.get("method"),
                    "path": scope.get("path"),
                    "route": getattr(route, "path", None),
                    "status": status_holder["status"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
