"""Dr. Flash — Core API Application.

FastAPI application with localhost binding, typed endpoints,
and service lifecycle management.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.config import settings
from services.core_api.routers import approvals, chat, health, knowledge, tasks, voice
from services.core_api.state import AppState
from services.telemetry import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down services."""
    setup_logging(settings.log_level)

    state = AppState()
    await state.initialize()
    app.state.drflash = state

    yield

    await state.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Dr. Flash Core API",
        description="Personal AI Operating System — Local API",
        version="0.2.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:7828", "http://127.0.0.1:7828"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(tasks.router)
    app.include_router(approvals.router)
    app.include_router(chat.router)
    app.include_router(voice.router)
    app.include_router(knowledge.router)

    return app


app = create_app()
