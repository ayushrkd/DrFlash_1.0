"""JARVIS — Execution Broker.

The trusted boundary between the LLM/orchestrator and actual tool execution.
Every tool call passes through the broker, which:
1. Validates the call against the tool registry
2. Checks policy (deny-by-default)
3. Obtains approval if required
4. Dispatches to the actual tool with a scoped capability token
5. Collects results and evidence
6. Sends to the verifier
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from services.contracts.enums import Risk, TaskStatus
from services.contracts.models import (
    CapabilityToken,
    PolicyDecision,
    TaskEvent,
    ToolCall,
    ToolRegistration,
    ToolResult,
    Verification,
)
from services.policy import PolicyEngine
from services.verifier import OutcomeVerifier


class ToolAdapter(ABC):
    """Base class for all tool implementations."""

    @property
    @abstractmethod
    def tool_id(self) -> str: ...

    @property
    @abstractmethod
    def registration(self) -> ToolRegistration: ...

    @abstractmethod
    async def execute(self, call: ToolCall, token: CapabilityToken) -> ToolResult: ...

    @abstractmethod
    async def observe(self, scope: str) -> dict: ...

    @abstractmethod
    async def health(self) -> dict: ...


class ExecutionBroker:
    """Central broker that authorizes, dispatches, and verifies tool calls."""

    def __init__(self, policy: PolicyEngine, verifier: OutcomeVerifier) -> None:
        self._policy = policy
        self._verifier = verifier
        self._adapters: dict[str, ToolAdapter] = {}
        self._audit_log: list[TaskEvent] = []

    def register_tool(self, adapter: ToolAdapter) -> None:
        reg = adapter.registration
        self._policy.register_tool(reg)
        self._adapters[reg.tool_id] = adapter

    def get_adapter(self, tool_id: str) -> ToolAdapter | None:
        return self._adapters.get(tool_id)

    def list_tools(self) -> list[ToolRegistration]:
        return self._policy.list_tools()

    async def dispatch(
        self, call: ToolCall, task_scope_ids: list[str] | None = None
    ) -> tuple[PolicyDecision, ToolResult | None, Verification | None]:
        """Full dispatch pipeline: policy -> execute -> verify."""

        # 1. Policy check
        decision = self._policy.evaluate(call, task_scope_ids)
        self._log_event(call.task_id, "broker.policy_checked", {
            "call_id": call.call_id,
            "tool_id": call.tool_id,
            "action": call.action,
            "allowed": decision.allowed,
            "risk": decision.risk.value,
            "reason": decision.reason,
        })

        if not decision.allowed:
            return decision, None, None

        if decision.requires_approval:
            self._log_event(call.task_id, "broker.approval_required", {
                "call_id": call.call_id,
                "risk": decision.risk.value,
            })
            return decision, None, None

        # 2. Validate capability token
        token = decision.capability_token
        if token is None:
            return PolicyDecision(
                allowed=False, risk=Risk.R4_DENY,
                reason="No capability token issued."
            ), None, None

        if not self._policy.validate_token(token):
            return PolicyDecision(
                allowed=False, risk=Risk.R4_DENY,
                reason="Capability token invalid or expired."
            ), None, None

        # 3. Dispatch to adapter
        adapter = self._adapters.get(call.tool_id)
        if adapter is None:
            return PolicyDecision(
                allowed=False, risk=Risk.R4_DENY,
                reason=f"No adapter found for tool '{call.tool_id}'."
            ), None, None

        start = time.monotonic()
        try:
            state_before = await adapter.observe(call.args.get("path", call.args.get("directory", "")))
            result = await adapter.execute(call, token)
            result.duration_ms = int((time.monotonic() - start) * 1000)
            state_after = await adapter.observe(call.args.get("path", call.args.get("directory", "")))
        except Exception as e:
            result = ToolResult(
                call_id=call.call_id,
                success=False,
                error=str(e),
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            self._log_event(call.task_id, "broker.execution_error", {
                "call_id": call.call_id, "error": str(e),
            })
            return decision, result, None

        # Mark token as used
        token.used = True

        self._log_event(call.task_id, "broker.executed", {
            "call_id": call.call_id,
            "success": result.success,
            "duration_ms": result.duration_ms,
        })

        # 4. Verify outcome
        verification = await self._verifier.verify(
            call=call,
            result=result,
            state_before=state_before,
            state_after=state_after,
        )

        self._log_event(call.task_id, "broker.verified", {
            "call_id": call.call_id,
            "passed": verification.passed,
            "checks": verification.checks,
        })

        return decision, result, verification

    def get_audit_log(self, task_id: str | None = None) -> list[TaskEvent]:
        if task_id:
            return [e for e in self._audit_log if e.task_id == task_id]
        return list(self._audit_log)

    def _log_event(self, task_id: str, event_type: str, data: dict) -> None:
        self._audit_log.append(TaskEvent(
            task_id=task_id,
            event_type=event_type,
            data=data,
        ))
