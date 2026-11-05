"""JARVIS — Memory Service (stub).

Placeholder for Phase 2. Provides the interface for personal memory
with provenance tracking, but stores nothing persistently yet.
"""

from __future__ import annotations

from datetime import datetime, timezone


class MemoryService:
    """Stub memory service — stores nothing until Phase 2."""

    def __init__(self) -> None:
        self._working_memory: dict[str, dict] = {}

    async def store_working(self, task_id: str, key: str, value: str) -> None:
        if task_id not in self._working_memory:
            self._working_memory[task_id] = {}
        self._working_memory[task_id][key] = {
            "value": value,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }

    async def recall_working(self, task_id: str, key: str) -> str | None:
        return self._working_memory.get(task_id, {}).get(key, {}).get("value")

    async def clear_working(self, task_id: str) -> None:
        self._working_memory.pop(task_id, None)

    async def search(self, query: str, scope: str | None = None) -> list[dict]:
        """Placeholder semantic search — returns empty until implemented."""
        return []
