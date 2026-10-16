from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import models  # noqa: F401  (register MVP tables)
from app.api import agent, orders, shipments, webhooks
from app.config import get_settings
from app.db import init_db
from app.domain.errors import DomainError
from app.mock_carriers import control, fastship, quickexpress, reliablecourier
from app.platform import models as platform_models  # noqa: F401  (register platform tables)
from app.platform.logging_setup import configure_logging
from app.platform.middleware import RequestContextMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    if get_settings().database_url.startswith("sqlite"):
        init_db()  # Postgres schemas are managed by Alembic migrations
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Zippyy", version="1.0.0", lifespan=lifespan,
                  docs_url=None if settings.is_production else "/docs",
                  redoc_url=None, openapi_url=None if settings.is_production else "/openapi.json")
    app.add_middleware(
        CORSMiddleware, allow_origins=[o for o in settings.cors_origins.split(",") if o], allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-Id", "Authorization", "Idempotency-Key"],
    )
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError):
        return JSONResponse(status_code=exc.http_status, content={"detail": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        # Echo field locations and messages only, never the submitted values (they may contain PII).
        errors = [{"loc": [str(p) for p in e.get("loc", [])], "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.get("/health")
    def health():
        return {"ok": True}

    from app.platform.api import router as platform_router
    app.include_router(platform_router)

    if settings.legacy_sandbox_enabled:
        # MVP booking sandbox and mock carriers (unauthenticated): development and demos only.
        for r in (orders.router, shipments.router, agent.router):
            app.include_router(r)
        for r in (fastship.router, quickexpress.router, reliablecourier.router, control.router):
            app.include_router(r)
    app.include_router(webhooks.router)  # carrier webhooks: signature-verified, always on
    return app


app = create_app()
