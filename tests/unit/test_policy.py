"""Unit tests for the Policy Engine."""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.contracts.enums import Risk, SideEffect
from services.contracts.models import ToolCall, ToolCapability, ToolRegistration
from services.policy import PolicyEngine


@pytest.fixture
def sandbox_dir(tmp_path: Path) -> Path:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "workspace").mkdir()
    (sandbox / "fixtures").mkdir()
    return sandbox


@pytest.fixture
def policy(sandbox_dir: Path) -> PolicyEngine:
    engine = PolicyEngine(allowed_paths=[str(sandbox_dir)])
    engine.register_tool(ToolRegistration(
        tool_id="sandbox.files",
        version="0.1.0",
        description="Sandbox file operations",
        capabilities=[
            ToolCapability(
                action="list_files",
                resource_scope=str(sandbox_dir),
                side_effect=SideEffect.READ,
                risk=Risk.R0_READ,
            ),
            ToolCapability(
                action="read_file",
                resource_scope=str(sandbox_dir),
                side_effect=SideEffect.READ,
                risk=Risk.R0_READ,
            ),
            ToolCapability(
                action="write_report",
                resource_scope=str(sandbox_dir / "workspace"),
                side_effect=SideEffect.LOCAL_WRITE,
                risk=Risk.R1_LOCAL_WRITE,
            ),
        ],
    ))
    return engine


class TestPolicyDenyByDefault:
    """Policy must deny unregistered tools, actions, and scopes."""

    def test_unregistered_tool_denied(self, policy: PolicyEngine):
        call = ToolCall(
            task_id="t1", tool_id="evil.tool", tool_version="0.1.0",
            action="hack", args={},
        )
        decision = policy.evaluate(call)
        assert not decision.allowed
        assert decision.risk == Risk.R4_DENY

    def test_unregistered_action_denied(self, policy: PolicyEngine):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="delete_everything", args={},
        )
        decision = policy.evaluate(call)
        assert not decision.allowed

    def test_version_mismatch_denied(self, policy: PolicyEngine):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="9.9.9",
            action="list_files", args={},
        )
        decision = policy.evaluate(call)
        assert not decision.allowed


class TestPolicyScopeEnforcement:
    """Policy must enforce resource scope boundaries."""

    def test_path_within_sandbox_allowed(self, policy: PolicyEngine, sandbox_dir: Path):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="list_files", args={"directory": str(sandbox_dir)},
        )
        decision = policy.evaluate(call)
        assert decision.allowed

    def test_path_outside_sandbox_denied(self, policy: PolicyEngine):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="read_file", args={"path": "C:\\Windows\\System32\\config\\sam"},
        )
        decision = policy.evaluate(call)
        assert not decision.allowed

    def test_path_traversal_denied(self, policy: PolicyEngine, sandbox_dir: Path):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="read_file", args={"path": str(sandbox_dir / ".." / ".." / "etc" / "passwd")},
        )
        decision = policy.evaluate(call)
        assert not decision.allowed

    def test_unc_path_denied(self, policy: PolicyEngine):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="read_file", args={"path": "\\\\evil-server\\share\\secret.txt"},
        )
        decision = policy.evaluate(call)
        assert not decision.allowed


class TestPolicyRiskTiers:
    """Policy must correctly classify risk and require approvals."""

    def test_read_auto_allowed(self, policy: PolicyEngine, sandbox_dir: Path):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="list_files", args={"directory": str(sandbox_dir)},
        )
        decision = policy.evaluate(call)
        assert decision.allowed
        assert decision.risk == Risk.R0_READ

    def test_local_write_allowed_with_token(self, policy: PolicyEngine, sandbox_dir: Path):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="write_report",
            args={"output_path": str(sandbox_dir / "workspace" / "test.md")},
        )
        decision = policy.evaluate(call)
        assert decision.allowed
        assert decision.capability_token is not None


class TestCapabilityToken:
    """Capability tokens must be single-use and time-bound."""

    def test_valid_token_accepted(self, policy: PolicyEngine, sandbox_dir: Path):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="list_files", args={"directory": str(sandbox_dir)},
        )
        decision = policy.evaluate(call)
        assert decision.capability_token is not None
        assert policy.validate_token(decision.capability_token)

    def test_used_token_rejected(self, policy: PolicyEngine, sandbox_dir: Path):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="list_files", args={"directory": str(sandbox_dir)},
        )
        decision = policy.evaluate(call)
        token = decision.capability_token
        assert token is not None
        token.used = True
        assert not policy.validate_token(token)

    def test_expired_token_rejected(self, policy: PolicyEngine, sandbox_dir: Path):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="list_files", args={"directory": str(sandbox_dir)},
        )
        decision = policy.evaluate(call)
        token = decision.capability_token
        assert token is not None
        token.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        assert not policy.validate_token(token)
