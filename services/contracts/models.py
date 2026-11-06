"""Core data models for DR_FLASH.

These Pydantic models define the canonical shapes for tasks, tool calls,
policy decisions, evidence, verification, and approvals. They are the
single source of truth shared across all services.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from ulid import ULID

from .enums import (
    ApprovalStatus,
    EvidenceKind,
    Risk,
    SideEffect,
    TaskStatus,
)


def _ulid() -> str:
    return str(ULID())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Capabilities & Tools ────────────────────────────────────────────

class ToolCapability(BaseModel):
    """Describes one action a tool can perform."""
    action: str
    resource_scope: str
    side_effect: SideEffect
    risk: Risk
    description: str = ""


class ToolRegistration(BaseModel):
    """A registered tool with its capabilities and constraints."""
    tool_id: str
    version: str
    description: str
    capabilities: list[ToolCapability]
    requires_approval_above: Risk = Risk.R0_READ
    execution_timeout_seconds: int = 30
    max_retries: int = 1


class ToolCall(BaseModel):
    """A specific invocation of a tool within a task."""
    call_id: str = Field(default_factory=_ulid)
    task_id: str
    step_id: str | None = None
    tool_id: str
    tool_version: str
    action: str
    args: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    expected_outcome: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class ToolResult(BaseModel):
    """Result of executing a tool call."""
    call_id: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
    completed_at: datetime = Field(default_factory=_now)


# ─── Policy ──────────────────────────────────────────────────────────

class CapabilityToken(BaseModel):
    """Scoped, time-bound authorization token for tool execution."""
    token_id: str = Field(default_factory=_ulid)
    task_id: str
    tool_id: str
    action: str
    resource_scope: str
    granted_by: str = "system"
    expires_at: datetime
    used: bool = False


class PolicyDecision(BaseModel):
    """Result of evaluating a tool call against policy."""
    decision_id: str = Field(default_factory=_ulid)
    allowed: bool
    requires_approval: bool = False
    risk: Risk
    reason: str
    capability_token: CapabilityToken | None = None
    decided_at: datetime = Field(default_factory=_now)


# ─── Evidence & Verification ─────────────────────────────────────────

class Evidence(BaseModel):
    """A piece of verification evidence collected after an action."""
    evidence_id: str = Field(default_factory=_ulid)
    kind: EvidenceKind
    source_id: str
    content: dict[str, Any] = Field(default_factory=dict)
    content_hash: str | None = None
    observed_at: datetime = Field(default_factory=_now)


class Verification(BaseModel):
    """Result of independently verifying an action's outcome."""
    verification_id: str = Field(default_factory=_ulid)
    passed: bool
    checks: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    uncertainty: str | None = None
    verified_at: datetime = Field(default_factory=_now)


# ─── Approvals ───────────────────────────────────────────────────────

class ApprovalRequest(BaseModel):
    """A request for human approval of a pending action."""
    approval_id: str = Field(default_factory=_ulid)
    task_id: str
    tool_call: ToolCall
    risk: Risk
    reason: str
    preview: dict[str, Any] = Field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)
    decided_at: datetime | None = None


# ─── Tasks ───────────────────────────────────────────────────────────

class TaskStep(BaseModel):
    """A single step in a task execution plan."""
    step_id: str = Field(default_factory=_ulid)
    task_id: str
    description: str
    tool_id: str | None = None
    action: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    expected_outcome: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.CREATED
    result: ToolResult | None = None
    verification: Verification | None = None
    order: int = 0


class TaskPlan(BaseModel):
    """An execution plan for a task."""
    plan_id: str = Field(default_factory=_ulid)
    task_id: str
    steps: list[TaskStep] = Field(default_factory=list)
    reasoning: str = ""
    created_at: datetime = Field(default_factory=_now)


class TaskEvent(BaseModel):
    """An append-only event recording task state changes and actions."""
    event_id: str = Field(default_factory=_ulid)
    task_id: str
    event_type: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_now)


class Task(BaseModel):
    """The canonical task entity."""
    task_id: str = Field(default_factory=_ulid)
    principal_id: str = "owner"
    status: TaskStatus = TaskStatus.CREATED
    input_text: str
    scope_ids: list[str] = Field(default_factory=list)
    plan: TaskPlan | None = None
    events: list[TaskEvent] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None
    max_tool_calls: int = Field(default=30, ge=0)
    max_cost_usd: float = Field(default=0.50, ge=0)
    max_seconds: int = Field(default=180, ge=0)
    model_usage: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


# ─── Model Router ────────────────────────────────────────────────────

class ModelRequest(BaseModel):
    """A request to a model provider."""
    request_id: str = Field(default_factory=_ulid)
    role: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    temperature: float = 0.1
    max_tokens: int = 2048
    task_id: str | None = None


class ModelResponse(BaseModel):
    """A response from a model provider."""
    request_id: str
    provider: str
    model: str
    content: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    finished_at: datetime = Field(default_factory=_now)
