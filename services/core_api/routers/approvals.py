"""Dr. Flash — Approval Queue Endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.contracts.enums import ApprovalStatus

router = APIRouter(prefix="/api/v1", tags=["approvals"])

# In-memory approval store for Phase 0
_pending_approvals: dict[str, dict] = {}


class ApprovalDecision(BaseModel):
    approved: bool
    reason: str = ""


@router.get("/approvals")
async def list_approvals() -> list[dict]:
    """List pending approval requests."""
    return [
        v for v in _pending_approvals.values()
        if v.get("status") == ApprovalStatus.PENDING
    ]


@router.post("/approvals/{approval_id}/decision")
async def decide_approval(approval_id: str, body: ApprovalDecision) -> dict:
    """Accept or reject a pending approval."""
    if approval_id not in _pending_approvals:
        raise HTTPException(status_code=404, detail="Approval not found")

    approval = _pending_approvals[approval_id]
    if approval["status"] != ApprovalStatus.PENDING:
        raise HTTPException(status_code=400, detail="Approval already decided")

    approval["status"] = ApprovalStatus.APPROVED if body.approved else ApprovalStatus.REJECTED
    approval["decision_reason"] = body.reason
    return approval
