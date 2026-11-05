"""JARVIS — Health and System Endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health")
async def health_check(request: Request) -> dict:
    """System health — no secrets exposed."""
    state = request.app.state.jarvis
    model_health = await state.model_router.health()
    return {
        "status": "healthy",
        "version": "0.1.0",
        "services": {
            "task_store": "connected",
            "policy_engine": "active",
            "execution_broker": {
                "tools_registered": len(state.broker.list_tools()),
            },
            "model_router": model_health,
            "memory": "stub",
        },
    }


@router.get("/api/v1/models")
async def list_models(request: Request) -> dict:
    """Available model roles and health."""
    state = request.app.state.jarvis
    return await state.model_router.health()


@router.get("/api/v1/tools")
async def list_tools(request: Request) -> list[dict]:
    """List registered tools and their capabilities."""
    state = request.app.state.jarvis
    tools = state.broker.list_tools()
    return [
        {
            "tool_id": t.tool_id,
            "version": t.version,
            "description": t.description,
            "capabilities": [
                {
                    "action": c.action,
                    "side_effect": c.side_effect.value,
                    "risk": c.risk.value,
                    "description": c.description,
                }
                for c in t.capabilities
            ],
        }
        for t in tools
    ]


@router.get("/api/v1/metrics/summary")
async def metrics_summary(request: Request) -> dict:
    """Cost/latency/success counters — no secrets."""
    state = request.app.state.jarvis
    return state.metrics.summary()


@router.get("/api/v1/privacy/status")
async def privacy_status() -> dict:
    """Recording/capture/cloud transmission state."""
    return {
        "microphone": "off",
        "screen_capture": "off",
        "cloud_streaming": "off",
        "local_wake_word": "off",
        "data_transmission": "none",
    }
