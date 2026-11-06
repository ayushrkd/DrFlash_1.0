"""Dr. Flash — Task Management Endpoints."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request

from services.contracts.enums import TaskStatus

router = APIRouter(prefix="/api/v1", tags=["tasks"])


class CreateTaskRequest(BaseModel):
    input_text: str
    scope_ids: list[str] = []


class TaskResponse(BaseModel):
    task_id: str
    status: str
    input_text: str
    created_at: str
    updated_at: str
    error: str | None = None


@router.post("/tasks", response_model=TaskResponse)
async def create_task(body: CreateTaskRequest, request: Request) -> TaskResponse:
    """Create a new task in Observe mode."""
    state = request.app.state.drflash
    task = await state.orchestrator.submit_task(body.input_text)
    return TaskResponse(
        task_id=task.task_id,
        status=task.status.value,
        input_text=task.input_text,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
        error=task.error,
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, request: Request) -> TaskResponse:
    """Get current task state."""
    state = request.app.state.drflash
    task = await state.task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse(
        task_id=task.task_id,
        status=task.status.value,
        input_text=task.input_text,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
        error=task.error,
    )


@router.get("/tasks")
async def list_tasks(request: Request, status: str | None = None, limit: int = 50) -> list[TaskResponse]:
    """List tasks, optionally filtered by status."""
    state = request.app.state.drflash
    task_status = TaskStatus(status) if status else None
    tasks = await state.task_store.list_tasks(status=task_status, limit=limit)
    return [
        TaskResponse(
            task_id=t.task_id,
            status=t.status.value,
            input_text=t.input_text,
            created_at=t.created_at.isoformat(),
            updated_at=t.updated_at.isoformat(),
            error=t.error,
        )
        for t in tasks
    ]


@router.post("/tasks/{task_id}/run")
async def run_task(task_id: str, request: Request) -> TaskResponse:
    """Execute a task through the full orchestration pipeline."""
    state = request.app.state.drflash
    task = await state.task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    result = await state.orchestrator.process_task(task_id)
    return TaskResponse(
        task_id=result.task_id,
        status=result.status.value,
        input_text=result.input_text,
        created_at=result.created_at.isoformat(),
        updated_at=result.updated_at.isoformat(),
        error=result.error,
    )


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request) -> TaskResponse:
    """Cancel a queued or active task."""
    state = request.app.state.drflash
    try:
        task = await state.orchestrator.cancel_task(task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return TaskResponse(
        task_id=task.task_id,
        status=task.status.value,
        input_text=task.input_text,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
        error=task.error,
    )


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request) -> list[dict]:
    """Get append-only event log for a task."""
    state = request.app.state.drflash
    events = await state.task_store.get_events(task_id)
    broker_events = state.broker.get_audit_log(task_id)
    all_events = [
        {
            "event_id": e.event_id,
            "task_id": e.task_id,
            "event_type": e.event_type,
            "data": e.data,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in events
    ] + [
        {
            "event_id": e.event_id,
            "task_id": e.task_id,
            "event_type": e.event_type,
            "data": e.data,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in broker_events
    ]
    return sorted(all_events, key=lambda e: e["timestamp"])
