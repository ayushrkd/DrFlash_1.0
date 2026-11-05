"""JARVIS — Deny-by-Default Policy Engine.

The policy engine is the trusted authorization boundary. It evaluates
every proposed tool call against risk tiers, resource scopes, and
approval requirements. It runs OUTSIDE the LLM — no model output
can bypass policy.

Design principles:
- Deny by default: any unregistered tool or unrecognized scope is denied.
- Risk-tiered: R0 (read) auto-allowed in scope, R1 (local write) may auto-allow,
  R2+ requires explicit approval.
- Scoped: resource paths are canonicalized and checked against allowed patterns.
- Time-bound: capability tokens expire.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from services.contracts.enums import Risk, SideEffect
from services.contracts.models import (
    CapabilityToken,
    PolicyDecision,
    ToolCall,
    ToolRegistration,
)


class PolicyEngine:
    """Deterministic, deny-by-default authorization engine."""

    def __init__(self, allowed_paths: list[str] | None = None) -> None:
        self._tool_registry: dict[str, ToolRegistration] = {}
        self._allowed_paths = [Path(p).resolve() for p in (allowed_paths or ["./sandbox"])]
        self._blocked_patterns: list[re.Pattern[str]] = [
            re.compile(r"\.\."),
            re.compile(r"~"),
            re.compile(r"\\\\"),  # UNC paths
        ]

    def register_tool(self, tool: ToolRegistration) -> None:
        self._tool_registry[tool.tool_id] = tool

    def get_tool(self, tool_id: str) -> ToolRegistration | None:
        return self._tool_registry.get(tool_id)

    def list_tools(self) -> list[ToolRegistration]:
        return list(self._tool_registry.values())

    def evaluate(self, call: ToolCall, task_scope_ids: list[str] | None = None) -> PolicyDecision:
        """Evaluate a tool call against policy. Returns allow/deny with reason."""

        tool = self._tool_registry.get(call.tool_id)
        if tool is None:
            return PolicyDecision(
                allowed=False,
                risk=Risk.R4_DENY,
                reason=f"Tool '{call.tool_id}' is not registered.",
            )

        if call.tool_version != tool.version:
            return PolicyDecision(
                allowed=False,
                risk=Risk.R4_DENY,
                reason=f"Tool version mismatch: expected {tool.version}, got {call.tool_version}.",
            )

        capability = None
        for cap in tool.capabilities:
            if cap.action == call.action:
                capability = cap
                break

        if capability is None:
            return PolicyDecision(
                allowed=False,
                risk=Risk.R4_DENY,
                reason=f"Action '{call.action}' not found in tool '{call.tool_id}'.",
            )

        if not self._check_resource_scope(call.args, capability.resource_scope):
            return PolicyDecision(
                allowed=False,
                risk=Risk.R4_DENY,
                reason="Resource scope violation: path not within allowed boundaries.",
            )

        if self._detect_path_traversal(call.args):
            return PolicyDecision(
                allowed=False,
                risk=Risk.R4_DENY,
                reason="Path traversal detected in arguments.",
            )

        risk = capability.risk
        requires_approval = risk.value >= tool.requires_approval_above.value and risk != Risk.R0_READ

        if risk == Risk.R4_DENY:
            return PolicyDecision(
                allowed=False,
                risk=risk,
                reason="Action is classified as R4_DENY and is never permitted.",
            )

        if risk in (Risk.R2_EXTERNAL_WRITE, Risk.R3_SENSITIVE):
            return PolicyDecision(
                allowed=False,
                requires_approval=True,
                risk=risk,
                reason=f"Action requires explicit approval (risk: {risk.value}).",
            )

        token = None
        if risk in (Risk.R0_READ, Risk.R1_LOCAL_WRITE):
            token = CapabilityToken(
                task_id=call.task_id,
                tool_id=call.tool_id,
                action=call.action,
                resource_scope=capability.resource_scope,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )

        return PolicyDecision(
            allowed=True,
            requires_approval=requires_approval,
            risk=risk,
            reason=f"Allowed: {capability.side_effect.value} within scope.",
            capability_token=token,
        )

    def validate_token(self, token: CapabilityToken) -> bool:
        """Check that a capability token is still valid."""
        if token.used:
            return False
        if datetime.now(timezone.utc) > token.expires_at:
            return False
        return True

    def _check_resource_scope(self, args: dict, scope: str) -> bool:
        """Verify that any path arguments fall within allowed boundaries.

        Relative paths are resolved against each allowed path to determine
        if they would land inside. This is critical because tools use relative
        paths within their sandbox root.
        """
        for key in ("path", "directory", "file_path", "output_path"):
            if key in args:
                raw = args[key]
                if not raw:
                    continue
                try:
                    candidate = Path(raw)
                    if candidate.is_absolute():
                        resolved = candidate.resolve()
                        if not any(self._is_subpath(resolved, a) for a in self._allowed_paths):
                            return False
                    else:
                        # Relative path: valid if it resolves inside ANY allowed path
                        if not any(
                            self._is_subpath((a / raw).resolve(), a)
                            for a in self._allowed_paths
                        ):
                            return False
                except (ValueError, OSError):
                    return False
        return True

    def _detect_path_traversal(self, args: dict) -> bool:
        """Detect path traversal attempts in any string argument."""
        for value in args.values():
            if isinstance(value, str):
                for pattern in self._blocked_patterns:
                    if pattern.search(value):
                        normalized = str(PurePosixPath(value))
                        if ".." in normalized:
                            return True
        return False

    @staticmethod
    def _is_subpath(child: Path, parent: Path) -> bool:
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False
