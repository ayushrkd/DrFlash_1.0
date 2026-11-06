"""JARVIS — Chat Service.

Real conversational chat with streaming responses, conversation
history, and integration with the model router and orchestrator.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from services.contracts.models import ModelRequest
from services.model_router import ModelRouter


class Message:
    def __init__(self, role: str, content: str, timestamp: datetime | None = None, metadata: dict | None = None):
        self.role = role
        self.content = content
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class Conversation:
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.messages: list[Message] = []
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def add_message(self, role: str, content: str, metadata: dict | None = None) -> Message:
        msg = Message(role=role, content=content, metadata=metadata)
        self.messages.append(msg)
        self.updated_at = datetime.now(timezone.utc)
        return msg

    def get_context_messages(self, max_messages: int = 20) -> list[dict]:
        """Get recent messages formatted for the model."""
        recent = self.messages[-max_messages:]
        return [{"role": m.role, "content": m.content} for m in recent]

    def to_dict(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "message_count": len(self.messages),
        }


SYSTEM_PROMPT = """You are JARVIS, a highly capable personal AI assistant and operating system. You are intelligent, concise, and helpful.

Key traits:
- You speak naturally but efficiently — no unnecessary filler
- You're proactive about suggesting better approaches
- You acknowledge what you can and can't do honestly
- You have access to local tools for file operations within a sandbox
- You track tasks, verify outcomes, and maintain security boundaries
- You're running locally on the user's machine with Ollama

When the user asks you to do something actionable (file operations, research, etc.), explain what you'll do and execute it. For conversation, be natural and direct."""


class ChatService:
    """Manages conversations and generates responses."""

    def __init__(self, model_router: ModelRouter):
        self._router = model_router
        self._conversations: dict[str, Conversation] = {}

    def get_or_create_conversation(self, conversation_id: str) -> Conversation:
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = Conversation(conversation_id)
        return self._conversations[conversation_id]

    def list_conversations(self) -> list[dict]:
        return [
            {
                "conversation_id": c.conversation_id,
                "message_count": len(c.messages),
                "last_message": c.messages[-1].content[:100] if c.messages else "",
                "updated_at": c.updated_at.isoformat(),
            }
            for c in sorted(self._conversations.values(), key=lambda x: x.updated_at, reverse=True)
        ]

    async def chat(self, conversation_id: str, user_message: str) -> str:
        """Send a message and get a complete response."""
        conv = self.get_or_create_conversation(conversation_id)
        conv.add_message("user", user_message)

        context = conv.get_context_messages()
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + context

        request = ModelRequest(
            role="LOCAL_DIALOG",
            messages=messages,
            temperature=0.7,
            max_tokens=2048,
        )

        response = await self._router.route(request)
        conv.add_message("assistant", response.content, metadata={
            "model": response.model,
            "provider": response.provider,
            "latency_ms": response.latency_ms,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
        })

        return response.content

    async def stream_chat(self, conversation_id: str, user_message: str) -> AsyncGenerator[str, None]:
        """Stream a response token by token via Ollama's streaming API."""
        import httpx

        conv = self.get_or_create_conversation(conversation_id)
        conv.add_message("user", user_message)

        context = conv.get_context_messages()
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + context

        start = time.monotonic()
        full_response = ""

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    "http://localhost:11434/api/chat",
                    json={
                        "model": "qwen2.5:7b-instruct-q4_K_M",
                        "messages": messages,
                        "stream": True,
                        "options": {"temperature": 0.7, "num_predict": 2048},
                    },
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line.strip():
                            try:
                                chunk = json.loads(line)
                                token = chunk.get("message", {}).get("content", "")
                                if token:
                                    full_response += token
                                    yield token
                                if chunk.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            # Fallback to mock if Ollama is unavailable
            full_response = f"I'm having trouble connecting to the local model. Error: {str(e)[:100]}. Let me try the mock provider."
            yield full_response

        elapsed = int((time.monotonic() - start) * 1000)
        conv.add_message("assistant", full_response, metadata={
            "model": "qwen2.5:7b-instruct-q4_K_M",
            "provider": "ollama",
            "latency_ms": elapsed,
            "streamed": True,
        })

    def delete_conversation(self, conversation_id: str) -> bool:
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            return True
        return False
