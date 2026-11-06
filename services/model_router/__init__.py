"""Dr. Flash — Model Router.

Abstract provider interface and routing logic. The router selects
the best model for each request based on role, complexity, privacy,
and budget constraints. Providers are pluggable.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from services.contracts.models import ModelRequest, ModelResponse


class ModelProvider(ABC):
    """Abstract base for all model providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def available_models(self) -> list[str]: ...

    @abstractmethod
    async def generate(self, request: ModelRequest) -> ModelResponse: ...

    @abstractmethod
    async def health(self) -> dict: ...


class MockProvider(ModelProvider):
    """Deterministic mock provider for testing and Phase 0."""

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def available_models(self) -> list[str]:
        return ["mock-fast", "mock-reasoning"]

    async def generate(self, request: ModelRequest) -> ModelResponse:
        start = time.monotonic()
        user_messages = [m for m in request.messages if m.get("role") == "user"]
        last_msg = user_messages[-1]["content"] if user_messages else ""

        content = self._generate_mock_response(last_msg, request.tools)

        elapsed = int((time.monotonic() - start) * 1000)
        return ModelResponse(
            request_id=request.request_id,
            provider="mock",
            model="mock-fast",
            content=content,
            input_tokens=len(str(request.messages)) // 4,
            output_tokens=len(content) // 4,
            latency_ms=elapsed,
            cost_usd=0.0,
        )

    def _generate_mock_response(self, user_msg: str, tools: list | None) -> str:
        lower = user_msg.lower()

        if tools:
            tool_names = [t.get("name", t.get("tool_id", "unknown")) for t in tools]
            if any(kw in lower for kw in ["list", "find", "show", "search"]):
                return f"I'll use the available tools to help: {', '.join(tool_names)}. Let me search for the relevant information."
            if any(kw in lower for kw in ["summarize", "report", "write", "create"]):
                return f"I'll create that for you using the available tools. Let me plan the steps needed."
            return f"I understand your request. I have access to: {', '.join(tool_names)}. How would you like me to proceed?"

        if any(kw in lower for kw in ["hello", "hi", "hey"]):
            return "Hello! I'm Dr. Flash, your personal AI assistant. How can I help you today?"
        if any(kw in lower for kw in ["summarize", "summary"]):
            return "I'll analyze the content and provide a structured summary with key findings."
        if any(kw in lower for kw in ["help", "what can you"]):
            return "I can help with file operations, research, code analysis, and task management — all within approved sandboxed boundaries."

        return f"I understand your request: '{user_msg[:100]}'. Let me plan the appropriate steps."

    async def health(self) -> dict:
        return {"status": "healthy", "provider": "mock", "models": self.available_models}


class OllamaProvider(ModelProvider):
    """Ollama local model provider."""

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self._base_url = base_url
        self._models: list[str] = []

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def available_models(self) -> list[str]:
        return self._models

    async def generate(self, request: ModelRequest) -> ModelResponse:
        import httpx

        start = time.monotonic()
        model = request.role  # Will be mapped by router

        # Map roles to actual model names
        role_model_map = {
            "FAST_INTENT": "llama3.2:3b",
            "LOCAL_DIALOG": "qwen2.5:7b-instruct-q4_K_M",
            "HARD_REASONING": "qwen2.5:7b-instruct-q4_K_M",
            "EMBEDDINGS": "nomic-embed-text:latest",
        }
        model = role_model_map.get(request.role, "qwen2.5:7b-instruct-q4_K_M")

        payload = {
            "model": model,
            "messages": request.messages,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        elapsed = int((time.monotonic() - start) * 1000)
        content = data.get("message", {}).get("content", "")
        eval_count = data.get("eval_count", len(content) // 4)
        prompt_eval_count = data.get("prompt_eval_count", 0)

        return ModelResponse(
            request_id=request.request_id,
            provider="ollama",
            model=model,
            content=content,
            input_tokens=prompt_eval_count,
            output_tokens=eval_count,
            latency_ms=elapsed,
            cost_usd=0.0,  # Local inference
        )

    async def health(self) -> dict:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                self._models = [m["name"] for m in data.get("models", [])]
                return {
                    "status": "healthy",
                    "provider": "ollama",
                    "models": self._models,
                }
        except Exception as e:
            return {"status": "unhealthy", "provider": "ollama", "error": str(e)}


class ModelRouter:
    """Routes requests to the best available provider based on role and constraints."""

    def __init__(self) -> None:
        self._providers: dict[str, ModelProvider] = {}
        self._role_routing: dict[str, str] = {}  # role -> provider_name
        self._total_cost_usd: float = 0.0
        self._total_requests: int = 0

    def register_provider(self, provider: ModelProvider) -> None:
        self._providers[provider.provider_name] = provider

    def set_role_routing(self, role: str, provider_name: str) -> None:
        self._role_routing[role] = provider_name

    async def route(self, request: ModelRequest) -> ModelResponse:
        provider_name = self._role_routing.get(request.role)
        if provider_name is None:
            # Fallback chain: try mock if nothing else configured
            provider_name = "mock" if "mock" in self._providers else next(iter(self._providers), None)

        if provider_name is None or provider_name not in self._providers:
            raise RuntimeError(f"No provider available for role '{request.role}'")

        provider = self._providers[provider_name]
        response = await provider.generate(request)

        self._total_cost_usd += response.cost_usd
        self._total_requests += 1

        return response

    async def health(self) -> dict:
        results = {}
        for name, provider in self._providers.items():
            results[name] = await provider.health()
        return {
            "providers": results,
            "total_cost_usd": self._total_cost_usd,
            "total_requests": self._total_requests,
        }
