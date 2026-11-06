"""JARVIS — Health and System Endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health")
async def health_check(request: Request) -> dict:
    """System health — no secrets exposed."""
    state = request.app.state.jarvis
    model_health = await state.model_router.health()
    uptime = int(time.time() - state.start_time)
    return {
        "status": "healthy",
        "version": "0.2.0",
        "uptime_seconds": uptime,
        "services": {
            "task_store": "connected",
            "policy_engine": "active",
            "chat_service": "active",
            "execution_broker": {
                "tools_registered": len(state.broker.list_tools()),
            },
            "model_router": model_health,
            "memory": "stub",
        },
    }


@router.get("/api/v1/system/status")
async def system_status(request: Request) -> dict:
    """Full system status for admin dashboard."""
    state = request.app.state.jarvis
    model_health = await state.model_router.health()
    uptime = int(time.time() - state.start_time)
    tasks = await state.task_store.list_tasks(limit=100)

    task_stats = {"total": len(tasks)}
    for t in tasks:
        task_stats[t.status.value] = task_stats.get(t.status.value, 0) + 1

    tools = state.broker.list_tools()
    conversations = state.chat.list_conversations()

    return {
        "system": {
            "status": "online",
            "version": "0.2.0",
            "uptime_seconds": uptime,
            "uptime_display": _format_uptime(uptime),
        },
        "models": model_health,
        "tasks": task_stats,
        "tools": [{"tool_id": t.tool_id, "capabilities": len(t.capabilities)} for t in tools],
        "conversations": {
            "active": len(conversations),
            "total_messages": sum(c.get("message_count", 0) for c in conversations),
        },
        "privacy": {
            "microphone": "off",
            "screen_capture": "off",
            "cloud_streaming": "off",
            "wake_word": "off",
        },
        "metrics": state.metrics.summary(),
    }


@router.get("/api/v1/system/activity")
async def system_activity(request: Request, limit: int = 50) -> list[dict]:
    """Recent activity feed for admin dashboard."""
    state = request.app.state.jarvis
    all_events = []

    # Get recent task events
    tasks = await state.task_store.list_tasks(limit=10)
    for task in tasks:
        events = await state.task_store.get_events(task.task_id)
        for e in events:
            all_events.append({
                "event_id": e.event_id,
                "type": e.event_type,
                "task_id": e.task_id,
                "data": e.data,
                "timestamp": e.timestamp.isoformat(),
            })

    # Get broker audit events
    for e in state.broker.get_audit_log():
        all_events.append({
            "event_id": e.event_id,
            "type": e.event_type,
            "task_id": e.task_id,
            "data": e.data,
            "timestamp": e.timestamp.isoformat(),
        })

    # Sort by time, newest first
    all_events.sort(key=lambda x: x["timestamp"], reverse=True)
    return all_events[:limit]


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


def _format_uptime(seconds: int) -> str:
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)
