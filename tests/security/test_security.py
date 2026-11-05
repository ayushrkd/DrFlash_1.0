"""Security and adversarial tests for JARVIS.

These tests verify that the system correctly blocks unauthorized
actions, path traversal, scope violations, and injection attempts.
"""

import pytest
from pathlib import Path

from services.contracts.enums import Risk
from services.contracts.models import ToolCall, ToolCapability, ToolRegistration
from services.contracts.enums import SideEffect
from services.execution_broker import ExecutionBroker
from services.execution_broker.tools.sandbox_files import SandboxFilesTool
from services.policy import PolicyEngine
from services.verifier import OutcomeVerifier


@pytest.fixture
def sandbox_dir(tmp_path: Path) -> Path:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "workspace").mkdir()
    (sandbox / "fixtures").mkdir()
    (sandbox / "fixtures" / "safe.txt").write_text("Safe content")
    return sandbox


@pytest.fixture
def system(sandbox_dir: Path):
    policy = PolicyEngine(allowed_paths=[str(sandbox_dir)])
    verifier = OutcomeVerifier()
    broker = ExecutionBroker(policy, verifier)
    broker.register_tool(SandboxFilesTool(sandbox_root=str(sandbox_dir)))
    return {"policy": policy, "broker": broker, "sandbox_dir": sandbox_dir}


class TestPathTraversal:
    """Verify all path traversal attempts are blocked."""

    @pytest.mark.asyncio
    async def test_dotdot_traversal(self, system):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="read_file", args={"path": "../../../etc/passwd"},
        )
        decision, result, _ = await system["broker"].dispatch(call)
        assert not decision.allowed

    @pytest.mark.asyncio
    async def test_absolute_path_outside(self, system):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="read_file", args={"path": "C:\\Windows\\System32\\cmd.exe"},
        )
        decision, result, _ = await system["broker"].dispatch(call)
        assert not decision.allowed

    @pytest.mark.asyncio
    async def test_unc_path(self, system):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="read_file", args={"path": "\\\\attacker\\share\\malware.exe"},
        )
        decision, result, _ = await system["broker"].dispatch(call)
        assert not decision.allowed


class TestUnauthorizedTools:
    """Verify unregistered tools and actions are denied."""

    @pytest.mark.asyncio
    async def test_unregistered_tool(self, system):
        call = ToolCall(
            task_id="t1", tool_id="system.shell", tool_version="1.0.0",
            action="execute", args={"command": "rm -rf /"},
        )
        decision, _, _ = await system["broker"].dispatch(call)
        assert not decision.allowed
        assert decision.risk == Risk.R4_DENY

    @pytest.mark.asyncio
    async def test_unregistered_action(self, system):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="delete_all", args={},
        )
        decision, _, _ = await system["broker"].dispatch(call)
        assert not decision.allowed

    @pytest.mark.asyncio
    async def test_version_mismatch(self, system):
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="99.0.0",
            action="list_files", args={"directory": "fixtures"},
        )
        decision, _, _ = await system["broker"].dispatch(call)
        assert not decision.allowed


class TestScopeIsolation:
    """Verify tools cannot escape their designated scope."""

    @pytest.mark.asyncio
    async def test_write_outside_workspace_denied(self, system):
        sandbox = system["sandbox_dir"]
        call = ToolCall(
            task_id="t1", tool_id="sandbox.files", tool_version="0.1.0",
            action="write_report",
            args={"output_path": "../../outside.txt", "content": "escape attempt"},
        )
        decision, result, _ = await system["broker"].dispatch(call)
        # Either policy blocks it or the tool itself rejects it
        if result:
            assert not result.success
        else:
            assert not decision.allowed


class TestAuditCompleteness:
    """Verify every action produces audit events."""

    @pytest.mark.asyncio
    async def test_denied_action_audited(self, system):
        call = ToolCall(
            task_id="audit-deny", tool_id="evil.tool", tool_version="1.0.0",
            action="hack", args={},
        )
        await system["broker"].dispatch(call)
        audit = system["broker"].get_audit_log("audit-deny")
        assert len(audit) >= 1
        assert any("policy" in e.event_type for e in audit)

    @pytest.mark.asyncio
    async def test_allowed_action_audited(self, system):
        call = ToolCall(
            task_id="audit-allow", tool_id="sandbox.files", tool_version="0.1.0",
            action="list_files", args={"directory": "fixtures"},
        )
        await system["broker"].dispatch(call)
        audit = system["broker"].get_audit_log("audit-allow")
        assert len(audit) >= 1  # At minimum: policy check
        event_types = [e.event_type for e in audit]
        assert "broker.policy_checked" in event_types