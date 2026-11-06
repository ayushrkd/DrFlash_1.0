"""Dr. Flash — Skills Framework.

Skills are learned, reusable procedures that DR_FLASH can execute.
They evolve through a lifecycle:

  DRAFT → QUARANTINE → TESTING → APPROVED → ACTIVE → DEPRECATED

Each skill has:
- A YAML manifest describing what it does
- A sequence of steps (tool calls, decisions, verifications)
- Preconditions and postconditions
- Success/failure metrics tracked over time
- Version history

Skills can be:
- Manually created by the user
- Induced from successful task completions
- Imported from a skill library
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

import aiosqlite
from ulid import ULID


class SkillStatus(StrEnum):
    DRAFT = "DRAFT"
    QUARANTINE = "QUARANTINE"
    TESTING = "TESTING"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    REVOKED = "REVOKED"


class SkillsService:
    """Manages the skill lifecycle, registry, and execution tracking."""

    def __init__(self, db_path: str = "./data/drflash.db",
                 skills_dir: str = "./data/skills") -> None:
        self._db_path = db_path
        self._skills_dir = Path(skills_dir)
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT '1.0.0',
                status TEXT NOT NULL DEFAULT 'DRAFT',
                trigger_patterns TEXT NOT NULL DEFAULT '[]',
                preconditions TEXT NOT NULL DEFAULT '[]',
                steps TEXT NOT NULL DEFAULT '[]',
                postconditions TEXT NOT NULL DEFAULT '[]',
                risk_level TEXT NOT NULL DEFAULT 'R0_READ',
                max_seconds INTEGER NOT NULL DEFAULT 60,
                max_tool_calls INTEGER NOT NULL DEFAULT 10,
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT NOT NULL DEFAULT 'system',
                source TEXT NOT NULL DEFAULT 'manual',
                metadata TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS skill_executions (
                id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                conversation_id TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                success BOOLEAN,
                duration_ms INTEGER,
                steps_completed INTEGER NOT NULL DEFAULT 0,
                steps_total INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                input_data TEXT NOT NULL DEFAULT '{}',
                output_data TEXT NOT NULL DEFAULT '{}',
                metadata TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (skill_id) REFERENCES skills(id)
            );

            CREATE TABLE IF NOT EXISTS skill_improvements (
                id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                improvement_type TEXT NOT NULL,
                description TEXT NOT NULL,
                before_value TEXT,
                after_value TEXT,
                detected_at TEXT NOT NULL,
                applied BOOLEAN NOT NULL DEFAULT 0,
                metadata TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (skill_id) REFERENCES skills(id)
            );

            CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status);
            CREATE INDEX IF NOT EXISTS idx_skill_exec_skill ON skill_executions(skill_id);
            CREATE INDEX IF NOT EXISTS idx_skill_improvements ON skill_improvements(skill_id);
        """)
        await self._db.commit()
        await self._create_default_skills()

    async def _create_default_skills(self) -> None:
        """Create built-in skills if they don't exist."""
        defaults = [
            {
                "name": "system_health_check",
                "description": "Check system health: CPU, RAM, GPU, disk, and running processes.",
                "trigger_patterns": ["system health", "check system", "system status", "how is my computer"],
                "steps": [
                    {"tool_id": "system.info", "action": "get_system_info", "args": {}},
                    {"tool_id": "system.info", "action": "get_disk_usage", "args": {}},
                    {"tool_id": "system.info", "action": "list_processes", "args": {"top_n": 10}},
                ],
                "tags": ["system", "diagnostic"],
            },
            {
                "name": "daily_briefing",
                "description": "Prepare a daily briefing with time, system status, and workspace overview.",
                "trigger_patterns": ["good morning", "daily briefing", "start my day", "what's the situation"],
                "steps": [
                    {"tool_id": "system.info", "action": "get_datetime", "args": {}},
                    {"tool_id": "system.info", "action": "get_system_info", "args": {}},
                    {"tool_id": "sandbox.files", "action": "list_files", "args": {"directory": "workspace"}},
                ],
                "tags": ["daily", "routine"],
            },
            {
                "name": "workspace_report",
                "description": "List and summarize all files in the sandbox workspace.",
                "trigger_patterns": ["workspace report", "list my files", "what's in workspace", "show workspace"],
                "steps": [
                    {"tool_id": "sandbox.files", "action": "list_files", "args": {"directory": "workspace"}},
                    {"tool_id": "sandbox.files", "action": "list_files", "args": {"directory": "fixtures"}},
                ],
                "tags": ["files", "workspace"],
            },
        ]

        for skill_def in defaults:
            existing = await self.get_skill_by_name(skill_def["name"])
            if not existing:
                await self.create_skill(
                    name=skill_def["name"],
                    description=skill_def["description"],
                    steps=skill_def["steps"],
                    trigger_patterns=skill_def["trigger_patterns"],
                    tags=skill_def.get("tags", []),
                    status=SkillStatus.APPROVED,
                    source="builtin",
                )

    # ─── Skill CRUD ──────────────────────────────────────────

    async def create_skill(
        self, name: str, description: str, steps: list[dict],
        trigger_patterns: list[str] | None = None,
        preconditions: list[str] | None = None,
        postconditions: list[str] | None = None,
        tags: list[str] | None = None,
        risk_level: str = "R0_READ",
        status: SkillStatus = SkillStatus.DRAFT,
        source: str = "manual",
    ) -> str:
        """Create a new skill."""
        skill_id = str(ULID())
        now = datetime.now(timezone.utc).isoformat()
        assert self._db
        await self._db.execute(
            """INSERT INTO skills (id, name, description, status, trigger_patterns,
               preconditions, steps, postconditions, risk_level, tags, created_at,
               updated_at, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (skill_id, name, description, status.value,
             json.dumps(trigger_patterns or []),
             json.dumps(preconditions or []),
             json.dumps(steps),
             json.dumps(postconditions or []),
             risk_level,
             json.dumps(tags or []),
             now, now, source)
        )
        await self._db.commit()

        # Save manifest to filesystem
        manifest = {
            "id": skill_id, "name": name, "description": description,
            "version": "1.0.0", "status": status.value,
            "trigger_patterns": trigger_patterns or [],
            "steps": steps, "tags": tags or [],
        }
        subdir = "approved" if status == SkillStatus.APPROVED else "quarantine"
        manifest_path = self._skills_dir / subdir / f"{name}.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2))

        return skill_id

    async def get_skill(self, skill_id: str) -> dict | None:
        assert self._db
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                result = dict(row)
                for key in ("trigger_patterns", "preconditions", "steps", "postconditions", "tags"):
                    result[key] = json.loads(result[key])
                result["metadata"] = json.loads(result["metadata"])
                return result
        return None

    async def get_skill_by_name(self, name: str) -> dict | None:
        assert self._db
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute("SELECT * FROM skills WHERE name = ?", (name,)) as cursor:
            row = await cursor.fetchone()
            if row:
                result = dict(row)
                for key in ("trigger_patterns", "preconditions", "steps", "postconditions", "tags"):
                    result[key] = json.loads(result[key])
                return result
        return None

    async def list_skills(self, status: SkillStatus | None = None) -> list[dict]:
        assert self._db
        self._db.row_factory = aiosqlite.Row
        if status:
            sql = "SELECT * FROM skills WHERE status = ? ORDER BY updated_at DESC"
            params = (status.value,)
        else:
            sql = "SELECT * FROM skills ORDER BY status, updated_at DESC"
            params = ()
        async with self._db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                r = dict(row)
                for key in ("trigger_patterns", "preconditions", "steps", "postconditions", "tags"):
                    r[key] = json.loads(r[key])
                results.append(r)
            return results

    async def match_skill(self, user_message: str) -> dict | None:
        """Find a matching skill based on trigger patterns."""
        skills = await self.list_skills(SkillStatus.APPROVED)
        skills += await self.list_skills(SkillStatus.ACTIVE)
        msg_lower = user_message.lower()

        best_match = None
        best_score = 0

        for skill in skills:
            for pattern in skill["trigger_patterns"]:
                if pattern.lower() in msg_lower:
                    score = len(pattern)
                    if score > best_score:
                        best_score = score
                        best_match = skill

        return best_match

    # ─── Execution Tracking ──────────────────────────────────

    async def record_execution(
        self, skill_id: str, success: bool, duration_ms: int,
        steps_completed: int, steps_total: int,
        input_data: dict | None = None, output_data: dict | None = None,
        error: str | None = None, conversation_id: str | None = None,
    ) -> str:
        """Record a skill execution for performance tracking."""
        exec_id = str(ULID())
        now = datetime.now(timezone.utc).isoformat()
        assert self._db
        await self._db.execute(
            """INSERT INTO skill_executions (id, skill_id, conversation_id, started_at,
               completed_at, success, duration_ms, steps_completed, steps_total,
               error, input_data, output_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (exec_id, skill_id, conversation_id, now, now, success, duration_ms,
             steps_completed, steps_total, error,
             json.dumps(input_data or {}), json.dumps(output_data or {}))
        )
        await self._db.commit()
        return exec_id

    async def get_skill_stats(self, skill_id: str) -> dict:
        """Get performance statistics for a skill."""
        assert self._db
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes,
                      AVG(duration_ms) as avg_duration,
                      MIN(duration_ms) as min_duration,
                      MAX(duration_ms) as max_duration
               FROM skill_executions WHERE skill_id = ?""",
            (skill_id,)
        ) as cursor:
            row = await cursor.fetchone()
            total = row["total"] or 0
            successes = row["successes"] or 0
            return {
                "total_executions": total,
                "success_count": successes,
                "failure_count": total - successes,
                "success_rate": successes / total if total > 0 else 0,
                "avg_duration_ms": round(row["avg_duration"] or 0),
                "min_duration_ms": row["min_duration"] or 0,
                "max_duration_ms": row["max_duration"] or 0,
            }

    # ─── Self-Improvement ────────────────────────────────────

    async def suggest_improvement(
        self, skill_id: str, improvement_type: str,
        description: str, before_value: str = "", after_value: str = "",
    ) -> str:
        """Record a suggested improvement for a skill."""
        imp_id = str(ULID())
        now = datetime.now(timezone.utc).isoformat()
        assert self._db
        await self._db.execute(
            """INSERT INTO skill_improvements (id, skill_id, improvement_type,
               description, before_value, after_value, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (imp_id, skill_id, improvement_type, description, before_value, after_value, now)
        )
        await self._db.commit()
        return imp_id

    async def get_context_for_chat(self) -> str:
        """Build skill context for the chat system prompt."""
        skills = await self.list_skills(SkillStatus.APPROVED)
        skills += await self.list_skills(SkillStatus.ACTIVE)
        if not skills:
            return ""

        lines = ["Available learned skills:"]
        for s in skills:
            triggers = ", ".join(s["trigger_patterns"][:3])
            lines.append(f"  - {s['name']}: {s['description']} (triggers: {triggers})")
        return "\n".join(lines)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
