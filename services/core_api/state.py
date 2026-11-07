"""Dr. Flash — Application State."""

from __future__ import annotations

import time

from services.chat import ChatService
from services.config import settings
from services.execution_broker import ExecutionBroker
from services.execution_broker.tools.app_tools import AppLauncherTool, CodeRunnerTool
from services.execution_broker.tools.productivity import MeetingTool, ProductivityTool, ScreenCaptureTool
from services.execution_broker.tools.sandbox_files import SandboxFilesTool
from services.execution_broker.tools.system_info import SystemInfoTool
from services.knowledge import KnowledgeService
from services.meetings import MeetingService
from services.memory import MemoryService
from services.model_router import MockProvider, ModelRouter, OllamaProvider
from services.orchestrator import Orchestrator
from services.policy import PolicyEngine
from services.screen import ScreenReader
from services.skills import SkillsService
from services.task_store import TaskStore
from services.telemetry import MetricsCollector
from services.verifier import OutcomeVerifier
from services.voice import VoiceEngine
from services.workspace import SelfImprovementLogger, WorkspaceManager


class AppState:
    """Central application state holding all service instances."""

    def __init__(self) -> None:
        db_path = "./data/drflash.db"

        self.task_store = TaskStore(db_path=db_path)
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

        # Knowledge & Skills
        self.knowledge = KnowledgeService(db_path=db_path)
        self.skills = SkillsService(db_path=db_path, skills_dir="./data/skills")

        # Workspace & Self-improvement
        self.workspace = WorkspaceManager(workspace_root="./data/workspace", db_path=db_path)
        self.improvement = SelfImprovementLogger(db_path=db_path)

        # Meetings
        self.meetings = MeetingService(meetings_dir="./data/meetings", db_path=db_path)

        # Screen reader
        self.screen = ScreenReader()

        # Chat service
        self.chat = ChatService(
            model_router=self.model_router,
            broker=self.broker,
            db_path=db_path,
        )

        # Voice engine
        self.voice = VoiceEngine()

        self.start_time = time.time()

    async def initialize(self) -> None:
        await self.task_store.initialize()
        self._register_tools()
        await self.chat.initialize()
        await self.knowledge.initialize()
        await self.skills.initialize()
        await self.workspace.initialize()
        await self.improvement.initialize()
        await self.meetings.initialize()

        self.chat._knowledge = self.knowledge
        self.chat._skills = self.skills
        self.chat._improvement = self.improvement

        health = await self._ollama_provider.health()
        if health.get("status") != "healthy":
            self.model_router.set_role_routing("FAST_INTENT", "mock")
            self.model_router.set_role_routing("LOCAL_DIALOG", "mock")
            self.model_router.set_role_routing("HARD_REASONING", "mock")

    def _register_tools(self) -> None:
        """Register all available tools with the broker."""
        self.broker.register_tool(SandboxFilesTool(sandbox_root=str(settings.sandbox_path)))
        self.broker.register_tool(SystemInfoTool())
        self.broker.register_tool(AppLauncherTool())
        self.broker.register_tool(CodeRunnerTool(sandbox_root=str(settings.sandbox_path)))
        self.broker.register_tool(ProductivityTool())
        self.broker.register_tool(ScreenCaptureTool())
        self.broker.register_tool(MeetingTool(self.meetings))

    async def shutdown(self) -> None:
        await self.task_store.close()
        await self.chat.close()
        await self.knowledge.close()
        await self.skills.close()
        await self.workspace.close()
        await self.improvement.close()
        await self.meetings.close()
