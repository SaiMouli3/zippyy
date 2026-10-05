from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import agent, orders, shipments, webhooks
from app.config import get_settings
from app.db import init_db
from app.domain.errors import DomainError
from app.mock_carriers import control, fastship, quickexpress, reliablecourier


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Zippy", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=get_settings().cors_origins.split(","), allow_methods=["*"], allow_headers=["*"]
    )

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError):
        return JSONResponse(status_code=exc.http_status, content={"detail": {"code": exc.code, "message": exc.message}})

    @app.get("/health")
    def health():
        return {"ok": True}

    for r in (orders.router, shipments.router, webhooks.router, agent.router):
        app.include_router(r)
    # Mock carriers: separate modules, mounted in-process for the MVP. Delete these lines once real carriers are used.
    for r in (fastship.router, quickexpress.router, reliablecourier.router, control.router):
        app.include_router(r)
    return app


app = create_app()
