"""Dr. Flash — Knowledge, Skills, and Self-Improvement API Endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.knowledge import KnowledgeScope, KnowledgeSource

router = APIRouter(prefix="/api/v1", tags=["knowledge"])


# ─── Knowledge ───────────────────────────────────────────────

class AddFactRequest(BaseModel):
    subject: str
    predicate: str
    object: str
    source: str = "USER_STATED"
    scope: str = "GENERAL"
    confidence: float = 1.0
    tags: list[str] = []


@router.post("/knowledge/facts")
async def add_fact(body: AddFactRequest, request: Request) -> dict:
    """Add a knowledge fact."""
    state = request.app.state.drflash
    fact_id = await state.knowledge.add_fact(
        subject=body.subject, predicate=body.predicate, obj=body.object,
        source=KnowledgeSource(body.source), scope=KnowledgeScope(body.scope),
        confidence=body.confidence, tags=body.tags,
    )
    return {"fact_id": fact_id, "status": "added"}


@router.get("/knowledge/facts")
async def search_facts(request: Request, query: str = "", scope: str | None = None) -> list[dict]:
    """Search knowledge facts."""
    state = request.app.state.drflash
    kscope = KnowledgeScope(scope) if scope else None
    return await state.knowledge.search_facts(query, scope=kscope)


@router.get("/knowledge/facts/{subject}")
async def get_facts_about(subject: str, request: Request) -> list[dict]:
    """Get all facts about a subject."""
    state = request.app.state.drflash
    return await state.knowledge.get_facts_about(subject)


@router.delete("/knowledge/facts/{fact_id}")
async def delete_fact(fact_id: str, request: Request) -> dict:
    """Delete a fact."""
    state = request.app.state.drflash
    await state.knowledge.delete_fact(fact_id)
    return {"deleted": True}


# ─── Preferences ─────────────────────────────────────────────

class SetPreferenceRequest(BaseModel):
    category: str
    key: str
    value: str


@router.post("/knowledge/preferences")
async def set_preference(body: SetPreferenceRequest, request: Request) -> dict:
    """Set a user preference."""
    state = request.app.state.drflash
    pref_id = await state.knowledge.set_preference(
        category=body.category, key=body.key, value=body.value,
        source=KnowledgeSource.USER_STATED, confidence=1.0,
    )
    return {"preference_id": pref_id, "status": "set"}


@router.get("/knowledge/preferences")
async def get_preferences(request: Request, category: str | None = None) -> list[dict]:
    """Get user preferences."""
    state = request.app.state.drflash
    return await state.knowledge.get_preferences(category)


@router.delete("/knowledge/preferences/{category}/{key}")
async def delete_preference(category: str, key: str, request: Request) -> dict:
    """Delete a preference."""
    state = request.app.state.drflash
    await state.knowledge.delete_preference(category, key)
    return {"deleted": True}


# ─── Skills ──────────────────────────────────────────────────

@router.get("/skills")
async def list_skills(request: Request, status: str | None = None) -> list[dict]:
    """List all skills."""
    state = request.app.state.drflash
    from services.skills import SkillStatus
    skill_status = SkillStatus(status) if status else None
    return await state.skills.list_skills(skill_status)


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, request: Request) -> dict:
    """Get skill details."""
    state = request.app.state.drflash
    skill = await state.skills.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    stats = await state.skills.get_skill_stats(skill_id)
    return {**skill, "stats": stats}


@router.get("/skills/{skill_id}/stats")
async def skill_stats(skill_id: str, request: Request) -> dict:
    """Get skill performance stats."""
    state = request.app.state.drflash
    return await state.skills.get_skill_stats(skill_id)


# ─── Workspace ───────────────────────────────────────────────

@router.get("/workspace")
async def list_workspace(request: Request, item_type: str | None = None) -> list[dict]:
    """List workspace items."""
    state = request.app.state.drflash
    return await state.workspace.list_items(item_type)


@router.get("/workspace/{item_id}")
async def get_workspace_item(item_id: str, request: Request) -> dict:
    """Read a workspace item."""
    state = request.app.state.drflash
    item = await state.workspace.read_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


# ─── Self-Improvement ────────────────────────────────────────

@router.get("/improvement/summary")
async def improvement_summary(request: Request) -> dict:
    """Get overall self-improvement metrics."""
    state = request.app.state.drflash
    return await state.improvement.get_summary()


@router.get("/improvement/daily")
async def daily_stats(request: Request, days: int = 7) -> list[dict]:
    """Get daily stats for the last N days."""
    state = request.app.state.drflash
    return await state.improvement.get_daily_stats(days)
