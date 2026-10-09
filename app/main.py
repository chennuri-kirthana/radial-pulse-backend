"""FastAPI application factory.

Middleware order (outermost first): request context → security headers → CORS → routes.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.contract import CONTRACT_VERSION
from app.core.error_handlers import register_error_handlers
from app.core.logging import configure_logging
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware

API_V1_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.service_name, settings.app_env, settings.service_version)

    app = FastAPI(
        title="Radial Pulse API",
        version=CONTRACT_VERSION,
        description=(
            "Platform API for Radial Pulse (clinics & practitioners). Every clinic-scoped route is "
            "authorized server-side; see docs/architecture/multi-tenancy.md."
        ),
        debug=settings.debug,
        docs_url="/docs" if settings.show_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.show_docs else None,
        separate_input_output_schemas=False,
    )

    register_error_handlers(app)

    # Added in reverse: the LAST added middleware runs FIRST.
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=False,  # bearer tokens, not cookies
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Clinic-ID"],
            expose_headers=["X-Request-ID"],
            max_age=600,
        )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.app_env in ("dev", "prod"))
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health_router)
    app.include_router(api_router, prefix=API_V1_PREFIX)
    return app


app = create_app()
