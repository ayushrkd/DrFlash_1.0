"""JARVIS — Intelligent Chat Service with Tool Calling.

This is the brain. The LLM receives the user's message along with
descriptions of available tools. It decides whether to respond directly
or invoke a tool. Tool results feed back into the conversation so
the LLM can form its final response.

Flow: User message → LLM (with tool descriptions) → tool call? →
      broker dispatch → result → LLM final response
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import aiosqlite

from services.contracts.models import ModelRequest, ToolCall
from services.execution_broker import ExecutionBroker
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


def _build_system_prompt(tools: list) -> str:
    """Build the system prompt with tool descriptions."""
    tool_block = ""
    for t in tools:
        tool_block += f"\n### Tool: {t.tool_id} (v{t.version})\n{t.description}\n"
        for c in t.capabilities:
            tool_block += f"  - Action: `{c.action}` — {c.description}\n"
            tool_block += f"    Risk: {c.risk.value} | Side effect: {c.side_effect.value}\n"

    return f"""You are JARVIS, an intelligent personal AI operating system running locally on the user's Windows machine.

## Your Capabilities
You have access to real tools that let you interact with the user's system. When the user asks you to DO something (open apps, search, check system info, work with files, run code), USE the tools.

## Available Tools
{tool_block}

## How to Use Tools
When you need to use a tool, output a tool call in this exact format on its own line:
```tool
{{"tool_id": "tool.name", "action": "action_name", "args": {{"key": "value"}}}}
```

You can use multiple tools by making multiple tool call blocks. After receiving tool results, provide a natural response summarizing what happened.

## Rules
- USE tools when the user asks to do something actionable. Don't just talk about it.
- Be concise and direct. No unnecessary filler.
- For file operations, work within the sandbox directory.
- For system info, actually fetch and report real data.
- If a tool fails, explain what happened and suggest alternatives.
- Never fabricate tool results. Only report what the tool actually returned.
- For dangerous operations, explain the risk and suggest safer alternatives.
- You run locally via Ollama — no data leaves the machine unless the user explicitly asks to open a URL."""


class ChatService:
    """Intelligent chat with tool calling, persistent conversations."""

    def __init__(self, model_router: ModelRouter, broker: ExecutionBroker | None = None,
                 db_path: str = "./data/jarvis.db") -> None:
        self._router = model_router
        self._broker = broker
        self._conversations: dict[str, Conversation] = {}
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Initialize persistent storage."""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                timestamp TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
            );
            CREATE INDEX IF NOT EXISTS idx_chat_conv ON chat_messages(conversation_id);
        """)
        await self._db.commit()
        # Load recent conversations into memory
        await self._load_recent_conversations()

    async def _load_recent_conversations(self) -> None:
        """Load recent conversations from DB."""
        if not self._db:
            return
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 20"
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                conv = Conversation(row["conversation_id"])
                conv.created_at = datetime.fromisoformat(row["created_at"])
                conv.updated_at = datetime.fromisoformat(row["updated_at"])
                # Load messages
                async with self._db.execute(
                    "SELECT * FROM chat_messages WHERE conversation_id = ? ORDER BY id ASC",
                    (row["conversation_id"],)
                ) as msg_cursor:
                    msg_rows = await msg_cursor.fetchall()
                    for mr in msg_rows:
                        conv.messages.append(Message(
                            role=mr["role"],
                            content=mr["content"],
                            timestamp=datetime.fromisoformat(mr["timestamp"]),
                            metadata=json.loads(mr["metadata"]),
                        ))
                self._conversations[conv.conversation_id] = conv

    async def _persist_message(self, conversation_id: str, role: str, content: str, metadata: dict) -> None:
        """Save a message to SQLite."""
        if not self._db:
            return
        now = datetime.now(timezone.utc).isoformat()
        # Upsert conversation
        await self._db.execute(
            "INSERT OR REPLACE INTO conversations (conversation_id, created_at, updated_at) VALUES (?, COALESCE((SELECT created_at FROM conversations WHERE conversation_id = ?), ?), ?)",
            (conversation_id, conversation_id, now, now)
        )
        await self._db.execute(
            "INSERT INTO chat_messages (conversation_id, role, content, metadata, timestamp) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, json.dumps(metadata), now)
        )
        await self._db.commit()

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

    def _get_tool_descriptions(self) -> list:
        """Get tool registrations from broker for the system prompt."""
        if self._broker:
            return self._broker.list_tools()
        return []

    def _extract_tool_calls(self, content: str) -> list[dict]:
        """Extract tool call JSON from LLM response."""
        calls = []
        # Look for ```tool ... ``` blocks
        pattern = r'```tool\s*\n?(.*?)\n?```'
        matches = re.findall(pattern, content, re.DOTALL)
        for match in matches:
            try:
                parsed = json.loads(match.strip())
                if "tool_id" in parsed and "action" in parsed:
                    calls.append(parsed)
            except json.JSONDecodeError:
                continue

        # Also look for inline JSON tool calls
        json_pattern = r'\{"tool_id":\s*"[^"]+",\s*"action":\s*"[^"]+"[^}]*\}'
        for match in re.finditer(json_pattern, content):
            try:
                parsed = json.loads(match.group())
                if parsed not in calls:
                    calls.append(parsed)
            except json.JSONDecodeError:
                continue

        return calls

    async def _execute_tool_call(self, tc: dict, conversation_id: str) -> dict:
        """Execute a tool call through the broker."""
        if not self._broker:
            return {"error": "No execution broker available"}

        tool_reg = self._broker._policy.get_tool(tc["tool_id"])
        if not tool_reg:
            return {"error": f"Tool '{tc['tool_id']}' not registered"}

        call = ToolCall(
            task_id=f"chat_{conversation_id}",
            tool_id=tc["tool_id"],
            tool_version=tool_reg.version,
            action=tc["action"],
            args=tc.get("args", {}),
        )

        decision, result, verification = await self._broker.dispatch(call)

        if not decision.allowed:
            return {"error": f"Policy denied: {decision.reason}", "risk": decision.risk.value}

        if result is None:
            return {"error": "No result — may require approval", "requires_approval": decision.requires_approval}

        return {
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "verified": verification.passed if verification else None,
            "duration_ms": result.duration_ms,
        }

    async def chat(self, conversation_id: str, user_message: str) -> str:
        """Send a message and get a complete response with tool execution."""
        conv = self.get_or_create_conversation(conversation_id)
        conv.add_message("user", user_message)
        await self._persist_message(conversation_id, "user", user_message, {})

        tools = self._get_tool_descriptions()
        system_prompt = _build_system_prompt(tools)
        context = conv.get_context_messages()
        messages = [{"role": "system", "content": system_prompt}] + context

        request = ModelRequest(
            role="LOCAL_DIALOG",
            messages=messages,
            temperature=0.4,
            max_tokens=2048,
        )

        response = await self._router.route(request)
        llm_content = response.content

        # Check if the LLM wants to use tools
        tool_calls = self._extract_tool_calls(llm_content)

        if tool_calls:
            # Execute tool calls and gather results
            tool_results = []
            for tc in tool_calls:
                result = await self._execute_tool_call(tc, conversation_id)
                tool_results.append({"tool": tc["tool_id"], "action": tc["action"], "result": result})

            # Feed results back to LLM for a natural response
            results_text = json.dumps(tool_results, indent=2, default=str)
            conv.add_message("assistant", llm_content, {"tool_calls": tool_calls})
            conv.add_message("system", f"Tool results:\n{results_text}")

            followup = ModelRequest(
                role="LOCAL_DIALOG",
                messages=[{"role": "system", "content": system_prompt}] +
                          conv.get_context_messages() +
                          [{"role": "user", "content": "Based on the tool results above, provide a clear natural response to the user. Don't repeat the raw JSON — summarize what happened."}],
                temperature=0.4,
                max_tokens=1024,
            )
            final_resp = await self._router.route(followup)
            final_content = final_resp.content

            # Replace the system message with the final response
            conv.messages.pop()  # Remove system tool results
            conv.messages.pop()  # Remove raw LLM with tool calls
            conv.add_message("assistant", final_content, {
                "model": final_resp.model,
                "provider": final_resp.provider,
                "latency_ms": response.latency_ms + final_resp.latency_ms,
                "tools_used": [tc["tool_id"] for tc in tool_calls],
                "tool_results": tool_results,
            })
            await self._persist_message(conversation_id, "assistant", final_content, {"tools_used": [tc["tool_id"] for tc in tool_calls]})
            return final_content

        # No tool calls — direct response
        conv.add_message("assistant", llm_content, {
            "model": response.model,
            "provider": response.provider,
            "latency_ms": response.latency_ms,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
        })
        await self._persist_message(conversation_id, "assistant", llm_content, {"model": response.model})
        return llm_content

    async def stream_chat(self, conversation_id: str, user_message: str) -> AsyncGenerator[str, None]:
        """Stream a response. For tool calls, execute first then stream the final response."""
        import httpx

        conv = self.get_or_create_conversation(conversation_id)
        conv.add_message("user", user_message)
        await self._persist_message(conversation_id, "user", user_message, {})

        tools = self._get_tool_descriptions()
        system_prompt = _build_system_prompt(tools)
        context = conv.get_context_messages()
        messages = [{"role": "system", "content": system_prompt}] + context

        start = time.monotonic()

        # First pass: get LLM response (non-streaming to check for tool calls)
        request = ModelRequest(
            role="LOCAL_DIALOG",
            messages=messages,
            temperature=0.4,
            max_tokens=2048,
        )
        response = await self._router.route(request)
        llm_content = response.content

        # Check for tool calls
        tool_calls = self._extract_tool_calls(llm_content)

        if tool_calls:
            # Signal tool execution to the user
            yield "🔧 Using tools: "
            tool_names = [f"`{tc['tool_id']}.{tc['action']}`" for tc in tool_calls]
            yield ", ".join(tool_names) + "\n\n"

            # Execute tools
            tool_results = []
            for tc in tool_calls:
                result = await self._execute_tool_call(tc, conversation_id)
                tool_results.append({"tool": tc["tool_id"], "action": tc["action"], "result": result})

            # Stream the follow-up response
            results_text = json.dumps(tool_results, indent=2, default=str)
            followup_messages = messages + [
                {"role": "assistant", "content": llm_content},
                {"role": "user", "content": f"Tool results:\n{results_text}\n\nBased on these results, provide a clear natural response. Don't repeat raw JSON — summarize and present the information clearly."},
            ]

            full_response = ""
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream(
                        "POST", "http://localhost:11434/api/chat",
                        json={
                            "model": "qwen2.5:7b-instruct-q4_K_M",
                            "messages": followup_messages,
                            "stream": True,
                            "options": {"temperature": 0.4, "num_predict": 1024},
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
                full_response = f"Error generating follow-up: {e}"
                yield full_response

            conv.add_message("assistant", full_response, {
                "tools_used": [tc["tool_id"] for tc in tool_calls],
                "tool_results": tool_results,
            })
            await self._persist_message(conversation_id, "assistant", full_response,
                                         {"tools_used": [tc["tool_id"] for tc in tool_calls]})
        else:
            # No tool calls — stream response directly
            full_response = ""
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream(
                        "POST", "http://localhost:11434/api/chat",
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
                full_response = f"Error: {e}"
                yield full_response

            elapsed = int((time.monotonic() - start) * 1000)
            conv.add_message("assistant", full_response, {
                "model": "qwen2.5:7b-instruct-q4_K_M",
                "provider": "ollama",
                "latency_ms": elapsed,
                "streamed": True,
            })
            await self._persist_message(conversation_id, "assistant", full_response, {"provider": "ollama"})

    def delete_conversation(self, conversation_id: str) -> bool:
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            return True
        return False

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
