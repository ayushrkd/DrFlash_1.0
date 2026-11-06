"""Dr. Flash — Durable Task Store.

SQLite-backed task persistence with state machine enforcement,
append-only event logging, and checkpoint/restart support.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from services.contracts.enums import VALID_TRANSITIONS, TaskStatus
from services.contracts.models import Task, TaskEvent


class TaskStoreError(Exception):
    pass


class InvalidTransitionError(TaskStoreError):
    pass


class TaskStore:
    """Async SQLite-backed task store with enforced state machine."""

    def __init__(self, db_path: str = "./data/drflash.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()

    async def _create_tables(self) -> None:
        assert self._db is not None
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                principal_id TEXT NOT NULL DEFAULT 'owner',
                status TEXT NOT NULL DEFAULT 'CREATED',
                input_text TEXT NOT NULL,
                scope_ids TEXT NOT NULL DEFAULT '[]',
                plan_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                max_tool_calls INTEGER NOT NULL DEFAULT 30,
                max_cost_usd REAL NOT NULL DEFAULT 0.50,
                max_seconds INTEGER NOT NULL DEFAULT 180,
                model_usage TEXT NOT NULL DEFAULT '{}',
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS task_events (
                event_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                data TEXT NOT NULL DEFAULT '{}',
                timestamp TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            );

            CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        """)
        await self._db.commit()

    async def create_task(self, task: Task) -> Task:
        assert self._db is not None
        await self._db.execute(
            """INSERT INTO tasks
               (task_id, principal_id, status, input_text, scope_ids,
                plan_json, created_at, updated_at, completed_at,
                max_tool_calls, max_cost_usd, max_seconds, model_usage, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.task_id,
                task.principal_id,
                task.status.value,
                task.input_text,
                json.dumps(task.scope_ids),
                task.plan.model_dump_json() if task.plan else None,
                task.created_at.isoformat(),
                task.updated_at.isoformat(),
                task.completed_at.isoformat() if task.completed_at else None,
                task.max_tool_calls,
                task.max_cost_usd,
                task.max_seconds,
                json.dumps(task.model_usage),
                task.error,
            ),
        )
        event = TaskEvent(
            task_id=task.task_id,
            event_type="task.created",
            data={"input_text": task.input_text, "status": task.status.value},
        )
        await self._append_event(event)
        await self._db.commit()
        return task

    async def get_task(self, task_id: str) -> Task | None:
        assert self._db is not None
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._row_to_task(row)

    async def list_tasks(
        self, status: TaskStatus | None = None, limit: int = 50
    ) -> list[Task]:
        assert self._db is not None
        self._db.row_factory = aiosqlite.Row
        if status:
            query = "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?"
            params = (status.value, limit)
        else:
            query = "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?"
            params = (limit,)
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    async def transition(
        self, task_id: str, new_status: TaskStatus, error: str | None = None
    ) -> Task:
        """Transition task state with enforcement of valid transitions."""
        task = await self.get_task(task_id)
        if task is None:
            raise TaskStoreError(f"Task {task_id} not found")

        current = task.status
        valid = VALID_TRANSITIONS.get(current, set())
        if new_status not in valid:
            raise InvalidTransitionError(
                f"Cannot transition from {current.value} to {new_status.value}. "
                f"Valid: {[s.value for s in valid]}"
            )

        now = datetime.now(timezone.utc)
        is_terminal = new_status in (
            TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED
        )
        completed_at_str = now.isoformat() if is_terminal else None

        assert self._db is not None
        await self._db.execute(
            """UPDATE tasks
               SET status = ?, updated_at = ?, completed_at = COALESCE(?, completed_at), error = ?
               WHERE task_id = ?""",
            (new_status.value, now.isoformat(), completed_at_str, error, task_id),
        )

        event = TaskEvent(
            task_id=task_id,
            event_type=f"task.transition.{new_status.value.lower()}",
            data={
                "from_status": current.value,
                "to_status": new_status.value,
                "error": error,
            },
        )
        await self._append_event(event)
        await self._db.commit()

        task.status = new_status
        task.updated_at = now
        task.error = error
        if is_terminal:
            task.completed_at = now
        return task

    async def update_plan(self, task_id: str, plan_json: str) -> None:
        assert self._db is not None
        now = datetime.now(timezone.utc)
        await self._db.execute(
            "UPDATE tasks SET plan_json = ?, updated_at = ? WHERE task_id = ?",
            (plan_json, now.isoformat(), task_id),
        )
        await self._append_event(TaskEvent(
            task_id=task_id,
            event_type="task.plan.updated",
            data={"plan_updated": True},
        ))
        await self._db.commit()

    async def get_events(self, task_id: str) -> list[TaskEvent]:
        assert self._db is not None
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            "SELECT * FROM task_events WHERE task_id = ? ORDER BY timestamp ASC",
            (task_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                TaskEvent(
                    event_id=row["event_id"],
                    task_id=row["task_id"],
                    event_type=row["event_type"],
                    data=json.loads(row["data"]),
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                )
                for row in rows
            ]

    async def _append_event(self, event: TaskEvent) -> None:
        assert self._db is not None
        await self._db.execute(
            """INSERT INTO task_events (event_id, task_id, event_type, data, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (
                event.event_id,
                event.task_id,
                event.event_type,
                json.dumps(event.data),
                event.timestamp.isoformat(),
            ),
        )

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @staticmethod
    def _row_to_task(row: aiosqlite.Row) -> Task:
        return Task(
            task_id=row["task_id"],
            principal_id=row["principal_id"],
            status=TaskStatus(row["status"]),
            input_text=row["input_text"],
            scope_ids=json.loads(row["scope_ids"]),
            plan=None,  # loaded on demand
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            max_tool_calls=row["max_tool_calls"],
            max_cost_usd=row["max_cost_usd"],
            max_seconds=row["max_seconds"],
            model_usage=json.loads(row["model_usage"]),
            error=row["error"],
        )
