"""JARVIS — Application State.

Manages the lifecycle of all services.
"""

from __future__ import annotations

import time

from services.chat import ChatService
from services.config import settings
from services.execution_broker import ExecutionBroker
from services.execution_broker.tools.app_tools import AppLauncherTool, CodeRunnerTool
from services.execution_broker.tools.sandbox_files import SandboxFilesTool
from services.execution_broker.tools.system_info import SystemInfoTool
from services.memory import MemoryService
from services.model_router import MockProvider, ModelRouter, OllamaProvider
from services.orchestrator import Orchestrator
from services.policy import PolicyEngine
from services.task_store import TaskStore
from services.telemetry import MetricsCollector
from services.verifier import OutcomeVerifier
from services.voice import VoiceEngine


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
        self.model_router.set_role_routing("FAST_INTENT", "ollama")
        self.model_router.set_role_routing("LOCAL_DIALOG", "ollama")
        self.model_router.set_role_routing("HARD_REASONING", "ollama")

        # Orchestrator
        self.orchestrator = Orchestrator(
            task_store=self.task_store,
            model_router=self.model_router,
            broker=self.broker,
        )

        # Chat service — connected to broker for real tool execution
        self.chat = ChatService(
            model_router=self.model_router,
            broker=self.broker,
            db_path="./data/jarvis.db",
        )

        # Voice engine
        self.voice = VoiceEngine()

        self.start_time = time.time()

    async def initialize(self) -> None:
        """Start all services."""
        await self.task_store.initialize()
        self._register_tools()
        await self.chat.initialize()

        health = await self._ollama_provider.health()
        if health.get("status") != "healthy":
            self.model_router.set_role_routing("FAST_INTENT", "mock")
            self.model_router.set_role_routing("LOCAL_DIALOG", "mock")
            self.model_router.set_role_routing("HARD_REASONING", "mock")

    def _register_tools(self) -> None:
        """Register all available tools with the broker."""
        # File operations (sandbox-scoped)
        self.broker.register_tool(SandboxFilesTool(sandbox_root=str(settings.sandbox_path)))

        # System info (read-only)
        self.broker.register_tool(SystemInfoTool())

        # App launcher and web search
        self.broker.register_tool(AppLauncherTool())

        # Sandboxed code runner
        self.broker.register_tool(CodeRunnerTool(sandbox_root=str(settings.sandbox_path)))

    async def shutdown(self) -> None:
        """Clean up resources."""
        await self.task_store.close()
        await self.chat.close()
