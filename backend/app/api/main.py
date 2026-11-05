"""The HTTP API the mobile app talks to.

Run from the repository root: `uvicorn app.api.main:app --app-dir backend --reload`.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from app.api import (
    actions,
    alarms,
    auth,
    chat,
    data,
    days,
    google,
    memory,
    notifications,
    reminders,
    reports,
    teams,
)
from app.api.errors import ApiError
from app.api.schemas import ErrorBody, ErrorResponse
from app.auth.accounts import AuthError
from app.background import Background
from app.config import settings
from app.ingest.takeout import IngestError

logger = logging.getLogger(__name__)


def _error(status: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message))
    return JSONResponse(status_code=status, content=body.model_dump(by_alias=True))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Background work that lives as long as the server: reminders, syncs and smart alarms."""
    loop = Background() if settings.reminders_enabled else None
    if loop:
        loop.start()
    yield
    if loop:
        loop.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Fitbit agent API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # Every error has the same shape: {"error": {"code": ..., "message": ...}}.
    @app.exception_handler(SQLAlchemyError)
    async def storage_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        # SQL errors can embed bound health payloads and credentials. Keep details out of logs.
        logger.error("A database operation failed")
        return _error(
            503,
            "storage_unavailable",
            "Data is temporarily unavailable. Refresh before trying again.",
        )

    @app.exception_handler(IngestError)
    async def ingest_error(_: Request, exc: IngestError) -> JSONResponse:
        logger.warning("Data unavailable: %s", exc)
        return _error(503, "data_unavailable", "Your Fitbit data could not be loaded.")

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(AuthError)
    async def auth_error(_: Request, exc: AuthError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(422, "invalid_request", "The request is not valid.")

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(actions.router)
    app.include_router(alarms.router)
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(google.router)
    app.include_router(data.router)
    app.include_router(days.router)
    app.include_router(notifications.router)
    app.include_router(memory.router)
    app.include_router(reminders.router)
    app.include_router(reports.router)
    app.include_router(teams.router)
    return app


app = create_app()
