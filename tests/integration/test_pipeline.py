"""Integration tests for the full task execution pipeline."""

import pytest
from pathlib import Path

from services.config import settings
from services.contracts.enums import TaskStatus
from services.contracts.models import Task
from services.execution_broker import ExecutionBroker
from services.execution_broker.tools.sandbox_files import SandboxFilesTool
from services.model_router import MockProvider, ModelRouter
from services.orchestrator import Orchestrator
from services.policy import PolicyEngine
from services.task_store import TaskStore
from services.verifier import OutcomeVerifier


@pytest.fixture
async def sandbox_dir(tmp_path: Path) -> Path:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "workspace").mkdir()
    (sandbox / "fixtures").mkdir()

    # Create test fixtures
    (sandbox / "fixtures" / "doc1.txt").write_text("Project Alpha status: on track. Budget: $50k.")
    (sandbox / "fixtures" / "doc2.txt").write_text("Meeting notes: discussed deployment timeline.")
    (sandbox / "fixtures" / "doc3.txt").write_text("Technical review: API performance is good.")
    return sandbox


@pytest.fixture
async def system(tmp_path: Path, sandbox_dir: Path):
    """Full system stack for integration tests."""
    db_path = str(tmp_path / "test.db")

    store = TaskStore(db_path=db_path)
    await store.initialize()

    policy = PolicyEngine(allowed_paths=[str(sandbox_dir)])
    verifier = OutcomeVerifier()
    broker = ExecutionBroker(policy, verifier)

    sandbox_tool = SandboxFilesTool(sandbox_root=str(sandbox_dir))
    broker.register_tool(sandbox_tool)

    router = ModelRouter()
    router.register_provider(MockProvider())
    router.set_role_routing("FAST_INTENT", "mock")
    router.set_role_routing("LOCAL_DIALOG", "mock")

    orchestrator = Orchestrator(store, router, broker)

    yield {
        "store": store,
        "policy": policy,
        "broker": broker,
        "router": router,
        "orchestrator": orchestrator,
        "sandbox_dir": sandbox_dir,
    }

    await store.close()


class TestEndToEndTaskExecution:
    @pytest.mark.asyncio
    async def test_submit_and_process_task(self, system):
        orch = system["orchestrator"]
        task = await orch.submit_task("List files in the sandbox")
        assert task.status == TaskStatus.CREATED

        result = await orch.process_task(task.task_id)
        assert result.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)

    @pytest.mark.asyncio
    async def test_task_events_recorded(self, system):
        orch = system["orchestrator"]
        store = system["store"]

        task = await orch.submit_task("Show me the fixture files")
        await orch.process_task(task.task_id)

        events = await store.get_events(task.task_id)
        assert len(events) >= 2  # At minimum: created + transitions

        event_types = [e.event_type for e in events]
        assert "task.created" in event_types

    @pytest.mark.asyncio
    async def test_task_cancellation(self, system):
        orch = system["orchestrator"]
        task = await orch.submit_task("A task to cancel")
        result = await orch.cancel_task(task.task_id)
        assert result.status == TaskStatus.CANCELLED


class TestSandboxFileOperations:
    @pytest.mark.asyncio
    async def test_list_sandbox_files(self, system):
        broker = system["broker"]
        sandbox_dir = system["sandbox_dir"]

        from services.contracts.models import ToolCall
        call = ToolCall(
            task_id="test-task",
            tool_id="sandbox.files",
            tool_version="0.1.0",
            action="list_files",
            args={"directory": "fixtures"},
        )

        decision, result, verification = await broker.dispatch(call)
        assert decision.allowed
        assert result is not None
        assert result.success
        assert len(result.data["files"]) == 3

    @pytest.mark.asyncio
    async def test_read_sandbox_file(self, system):
        broker = system["broker"]

        from services.contracts.models import ToolCall
        call = ToolCall(
            task_id="test-task",
            tool_id="sandbox.files",
            tool_version="0.1.0",
            action="read_file",
            args={"path": "fixtures/doc1.txt"},
        )

        decision, result, verification = await broker.dispatch(call)
        assert decision.allowed
        assert result is not None
        assert result.success
        assert "Project Alpha" in result.data["content"]

    @pytest.mark.asyncio
    async def test_write_report_to_workspace(self, system):
        broker = system["broker"]
        sandbox_dir = system["sandbox_dir"]

        from services.contracts.models import ToolCall
        call = ToolCall(
            task_id="test-task",
            tool_id="sandbox.files",
            tool_version="0.1.0",
            action="write_report",
            args={
                "output_path": "test_report.md",
                "content": "# Test Report\n\nThis is a verified test report.",
            },
        )

        decision, result, verification = await broker.dispatch(call)
        assert decision.allowed
        assert result is not None
        assert result.success

        # Verify file actually exists
        report_path = sandbox_dir / "workspace" / "test_report.md"
        assert report_path.exists()
        assert "Test Report" in report_path.read_text()


class TestAuditTrail:
    @pytest.mark.asyncio
    async def test_all_actions_audited(self, system):
        broker = system["broker"]

        from services.contracts.models import ToolCall
        call = ToolCall(
            task_id="audit-test",
            tool_id="sandbox.files",
            tool_version="0.1.0",
            action="list_files",
            args={"directory": "fixtures"},
        )

        await broker.dispatch(call)
        audit = broker.get_audit_log("audit-test")
        assert len(audit) >= 1
        event_types = [e.event_type for e in audit]
        assert "broker.policy_checked" in event_types
