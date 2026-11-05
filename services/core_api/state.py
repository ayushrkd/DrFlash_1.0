"""JARVIS — Application State.

Manages the lifecycle of all services. Created once at startup,
available via `request.app.state.jarvis`.
"""

from __future__ import annotations

from services.config import settings
from services.execution_broker import ExecutionBroker
from services.execution_broker.tools.sandbox_files import SandboxFilesTool
from services.memory import MemoryService
from services.model_router import MockProvider, ModelRouter, OllamaProvider
from services.orchestrator import Orchestrator
from services.policy import PolicyEngine
from services.task_store import TaskStore
from services.telemetry import MetricsCollector
from services.verifier import OutcomeVerifier


class AppState:
    """Central application state holding all service instances."""

    def __init__(self) -> None:
        self.task_store = TaskStore(db_path="./data/jarvis.db")
        self.policy = PolicyEngine(allowed_paths=[str(settings.sandbox_path)])
        self.verifier = OutcomeVerifier()
        self.broker = ExecutionBroker(self.policy, self.verifier)
        self.memory = MemoryService()
        self.metrics = MetricsCollector()

        # Model router
        self.model_router = ModelRouter()
        self._mock_provider = MockProvider()
        self._ollama_provider = OllamaProvider()
        self.model_router.register_provider(self._mock_provider)
        self.model_router.register_provider(self._ollama_provider)

        # Default routing: use mock for now (safe, no dependencies)
        self.model_router.set_role_routing("FAST_INTENT", "mock")
        self.model_router.set_role_routing("LOCAL_DIALOG", "mock")
        self.model_router.set_role_routing("HARD_REASONING", "mock")

        # Orchestrator
        self.orchestrator = Orchestrator(
            task_store=self.task_store,
            model_router=self.model_router,
            broker=self.broker,
        )

    async def initialize(self) -> None:
        """Start all services."""
        await self.task_store.initialize()
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all available tools with the broker."""
        sandbox_tool = SandboxFilesTool(sandbox_root=str(settings.sandbox_path))
        self.broker.register_tool(sandbox_tool)

    async def shutdown(self) -> None:
        """Clean up resources."""
        await self.task_store.close()
