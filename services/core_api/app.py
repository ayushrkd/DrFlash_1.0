"""JARVIS — Core API Application.

FastAPI application with localhost binding, typed endpoints,
and service lifecycle management.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.config import settings
from services.core_api.routers import approvals, health, tasks
from services.core_api.state import AppState
from services.telemetry import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down services."""
    setup_logging(settings.log_level)

    state = AppState()
    await state.initialize()
    app.state.jarvis = state

    yield

    await state.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="JARVIS Core API",
        description="Personal AI Operating System — Local API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Only allow localhost origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(tasks.router)
    app.include_router(approvals.router)

    return app


app = create_app()
