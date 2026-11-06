"""Dr. Flash — Knowledge Service.

Long-term memory with provenance tracking. Stores facts, entities,
relationships, and user preferences. Every piece of knowledge has:
- Source: where did this come from?
- Confidence: how sure are we?
- Temporal: when was this true? Is it still valid?
- Scope: personal, project, general?

Knowledge lifecycle:
  OBSERVED → CANDIDATE → CONFIRMED → ACTIVE → SUPERSEDED/EXPIRED/DELETED

User corrections always override inferred knowledge.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import StrEnum

import aiosqlite
from ulid import ULID


class KnowledgeStatus(StrEnum):
    OBSERVED = "OBSERVED"
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class KnowledgeSource(StrEnum):
    USER_STATED = "USER_STATED"          # User explicitly told DR_FLASH
    USER_CONFIRMED = "USER_CONFIRMED"    # DR_FLASH inferred, user confirmed
    INFERRED = "INFERRED"                # DR_FLASH inferred from interactions
    EXTRACTED = "EXTRACTED"              # Extracted from a document/file
    SYSTEM = "SYSTEM"                    # System-level fact


class KnowledgeScope(StrEnum):
    PERSONAL = "PERSONAL"       # About the user
    PROJECT = "PROJECT"         # About a specific project
    GENERAL = "GENERAL"         # General world knowledge
    PREFERENCE = "PREFERENCE"   # User preference
    SKILL = "SKILL"             # Learned procedure


class KnowledgeService:
    """Persistent knowledge with provenance, temporal awareness, and corrections."""

    def __init__(self, db_path: str = "./data/drflash.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'INFERRED',
                source_detail TEXT,
                scope TEXT NOT NULL DEFAULT 'GENERAL',
                status TEXT NOT NULL DEFAULT 'CANDIDATE',
                confidence REAL NOT NULL DEFAULT 0.5,
                valid_from TEXT,
                valid_until TEXT,
                observed_at TEXT NOT NULL,
                confirmed_at TEXT,
                superseded_by TEXT,
                tags TEXT NOT NULL DEFAULT '[]',
                metadata TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS preferences (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'INFERRED',
                confidence REAL NOT NULL DEFAULT 0.5,
                confirmed BOOLEAN NOT NULL DEFAULT 0,
                observed_at TEXT NOT NULL,
                confirmed_at TEXT,
                usage_count INTEGER NOT NULL DEFAULT 0,
                last_used TEXT,
                metadata TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                description TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                mention_count INTEGER NOT NULL DEFAULT 1,
                attributes TEXT NOT NULL DEFAULT '{}',
                relationships TEXT NOT NULL DEFAULT '[]'
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_subject ON knowledge(subject);
            CREATE INDEX IF NOT EXISTS idx_knowledge_status ON knowledge(status);
            CREATE INDEX IF NOT EXISTS idx_knowledge_scope ON knowledge(scope);
            CREATE INDEX IF NOT EXISTS idx_preferences_category ON preferences(category);
            CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
            CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
        """)
        await self._db.commit()

    # ─── Knowledge CRUD ──────────────────────────────────────

    async def add_fact(
        self, subject: str, predicate: str, obj: str,
        source: KnowledgeSource = KnowledgeSource.INFERRED,
        source_detail: str | None = None,
        scope: KnowledgeScope = KnowledgeScope.GENERAL,
        confidence: float = 0.5,
        tags: list[str] | None = None,
    ) -> str:
        """Add a knowledge fact. Returns the fact ID."""
        fact_id = str(ULID())
        now = datetime.now(timezone.utc).isoformat()
        status = KnowledgeStatus.CONFIRMED if source == KnowledgeSource.USER_STATED else KnowledgeStatus.CANDIDATE

        assert self._db
        await self._db.execute(
            """INSERT INTO knowledge (id, subject, predicate, object, source, source_detail,
               scope, status, confidence, observed_at, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fact_id, subject, predicate, obj, source.value, source_detail,
             scope.value, status.value, confidence, now, json.dumps(tags or []))
        )
        await self._db.commit()
        return fact_id

    async def confirm_fact(self, fact_id: str) -> bool:
        """User confirms an inferred fact."""
        assert self._db
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE knowledge SET status = ?, confidence = 1.0, confirmed_at = ? WHERE id = ?",
            (KnowledgeStatus.CONFIRMED.value, now, fact_id)
        )
        await self._db.commit()
        return True

    async def correct_fact(self, fact_id: str, new_object: str) -> str:
        """User corrects a fact. Old fact is superseded, new one created."""
        assert self._db
        now = datetime.now(timezone.utc).isoformat()

        # Get original fact
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute("SELECT * FROM knowledge WHERE id = ?", (fact_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return ""

        # Supersede old
        new_id = str(ULID())
        await self._db.execute(
            "UPDATE knowledge SET status = ?, superseded_by = ? WHERE id = ?",
            (KnowledgeStatus.SUPERSEDED.value, new_id, fact_id)
        )

        # Create corrected version
        await self._db.execute(
            """INSERT INTO knowledge (id, subject, predicate, object, source, source_detail,
               scope, status, confidence, observed_at, confirmed_at, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_id, row["subject"], row["predicate"], new_object,
             KnowledgeSource.USER_STATED.value, f"Corrected from {fact_id}",
             row["scope"], KnowledgeStatus.CONFIRMED.value, 1.0, now, now, row["tags"])
        )
        await self._db.commit()
        return new_id

    async def search_facts(
        self, query: str, scope: KnowledgeScope | None = None, limit: int = 20
    ) -> list[dict]:
        """Search knowledge by keyword in subject/predicate/object."""
        assert self._db
        self._db.row_factory = aiosqlite.Row
        q = f"%{query}%"
        if scope:
            sql = """SELECT * FROM knowledge WHERE status IN ('CONFIRMED', 'ACTIVE', 'CANDIDATE')
                     AND scope = ? AND (subject LIKE ? OR predicate LIKE ? OR object LIKE ?)
                     ORDER BY confidence DESC, observed_at DESC LIMIT ?"""
            params = (scope.value, q, q, q, limit)
        else:
            sql = """SELECT * FROM knowledge WHERE status IN ('CONFIRMED', 'ACTIVE', 'CANDIDATE')
                     AND (subject LIKE ? OR predicate LIKE ? OR object LIKE ?)
                     ORDER BY confidence DESC, observed_at DESC LIMIT ?"""
            params = (q, q, q, limit)

        async with self._db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_facts_about(self, subject: str, limit: int = 20) -> list[dict]:
        """Get all known facts about a subject."""
        assert self._db
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            """SELECT * FROM knowledge WHERE subject = ? AND status IN ('CONFIRMED', 'ACTIVE', 'CANDIDATE')
               ORDER BY confidence DESC LIMIT ?""",
            (subject, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def delete_fact(self, fact_id: str) -> bool:
        """User deletes a fact permanently."""
        assert self._db
        await self._db.execute(
            "UPDATE knowledge SET status = ? WHERE id = ?",
            (KnowledgeStatus.DELETED.value, fact_id)
        )
        await self._db.commit()
        return True

    # ─── Preferences ─────────────────────────────────────────

    async def set_preference(
        self, category: str, key: str, value: str,
        source: KnowledgeSource = KnowledgeSource.INFERRED,
        confidence: float = 0.5,
    ) -> str:
        """Set or update a preference."""
        assert self._db
        pref_id = str(ULID())
        now = datetime.now(timezone.utc).isoformat()
        confirmed = source in (KnowledgeSource.USER_STATED, KnowledgeSource.USER_CONFIRMED)

        # Check if preference already exists
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            "SELECT id FROM preferences WHERE category = ? AND key = ?", (category, key)
        ) as cursor:
            existing = await cursor.fetchone()

        if existing:
            await self._db.execute(
                """UPDATE preferences SET value = ?, confidence = ?, confirmed = ?,
                   last_used = ?, usage_count = usage_count + 1 WHERE category = ? AND key = ?""",
                (value, max(confidence, 0.5 if not confirmed else 1.0), confirmed, now, category, key)
            )
            pref_id = existing["id"]
        else:
            await self._db.execute(
                """INSERT INTO preferences (id, category, key, value, source, confidence,
                   confirmed, observed_at, last_used)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pref_id, category, key, value, source.value, confidence, confirmed, now, now)
            )
        await self._db.commit()
        return pref_id

    async def get_preference(self, category: str, key: str) -> str | None:
        """Get a specific preference value."""
        assert self._db
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            "SELECT value FROM preferences WHERE category = ? AND key = ?", (category, key)
        ) as cursor:
            row = await cursor.fetchone()
            return row["value"] if row else None

    async def get_preferences(self, category: str | None = None) -> list[dict]:
        """Get all preferences, optionally filtered by category."""
        assert self._db
        self._db.row_factory = aiosqlite.Row
        if category:
            sql = "SELECT * FROM preferences WHERE category = ? ORDER BY usage_count DESC"
            params = (category,)
        else:
            sql = "SELECT * FROM preferences ORDER BY category, usage_count DESC"
            params = ()
        async with self._db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def delete_preference(self, category: str, key: str) -> bool:
        assert self._db
        await self._db.execute("DELETE FROM preferences WHERE category = ? AND key = ?", (category, key))
        await self._db.commit()
        return True

    # ─── Entities ─────────────────────────────────────────────

    async def track_entity(
        self, name: str, entity_type: str, description: str = "",
        attributes: dict | None = None,
    ) -> str:
        """Track or update an entity (person, project, tool, etc.)."""
        assert self._db
        now = datetime.now(timezone.utc).isoformat()
        self._db.row_factory = aiosqlite.Row

        async with self._db.execute(
            "SELECT id FROM entities WHERE name = ? AND entity_type = ?", (name, entity_type)
        ) as cursor:
            existing = await cursor.fetchone()

        if existing:
            await self._db.execute(
                """UPDATE entities SET last_seen = ?, mention_count = mention_count + 1,
                   description = COALESCE(?, description),
                   attributes = ? WHERE id = ?""",
                (now, description or None, json.dumps(attributes or {}), existing["id"])
            )
            return existing["id"]

        entity_id = str(ULID())
        await self._db.execute(
            """INSERT INTO entities (id, name, entity_type, description, first_seen, last_seen, attributes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (entity_id, name, entity_type, description, now, now, json.dumps(attributes or {}))
        )
        await self._db.commit()
        return entity_id

    async def search_entities(self, query: str, entity_type: str | None = None) -> list[dict]:
        assert self._db
        self._db.row_factory = aiosqlite.Row
        q = f"%{query}%"
        if entity_type:
            sql = "SELECT * FROM entities WHERE entity_type = ? AND name LIKE ? ORDER BY mention_count DESC LIMIT 20"
            params = (entity_type, q)
        else:
            sql = "SELECT * FROM entities WHERE name LIKE ? ORDER BY mention_count DESC LIMIT 20"
            params = (q,)
        async with self._db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ─── Context for Chat ─────────────────────────────────────

    async def get_context_for_chat(self, user_message: str) -> str:
        """Build relevant knowledge context for the chat system prompt."""
        context_parts = []

        # Get user preferences
        prefs = await self.get_preferences()
        if prefs:
            pref_lines = [f"  - {p['category']}/{p['key']}: {p['value']}" for p in prefs[:10]]
            context_parts.append("User preferences:\n" + "\n".join(pref_lines))

        # Search relevant facts
        words = user_message.split()[:5]  # Use first 5 words as search terms
        for word in words:
            if len(word) > 3:
                facts = await self.search_facts(word, limit=3)
                for f in facts:
                    context_parts.append(
                        f"Known fact: {f['subject']} {f['predicate']} {f['object']} "
                        f"(source: {f['source']}, confidence: {f['confidence']})"
                    )

        return "\n".join(context_parts) if context_parts else ""

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
