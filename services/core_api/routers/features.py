"""Dr. Flash — Meeting & Screen Reader API Endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["meetings", "screen"])


# ─── Meetings ────────────────────────────────────────────────

class StartRecordingRequest(BaseModel):
    title: str
    participants: list[str] = []
    tags: list[str] = []


@router.post("/meetings/start")
async def start_recording(body: StartRecordingRequest, request: Request) -> dict:
    state = request.app.state.drflash
    return await state.meetings.start_recording(body.title, body.participants, body.tags)


@router.post("/meetings/stop")
async def stop_recording(request: Request) -> dict:
    state = request.app.state.drflash
    return await state.meetings.stop_recording()


@router.get("/meetings/status")
async def recording_status(request: Request) -> dict:
    state = request.app.state.drflash
    return state.meetings.recording_status


@router.get("/meetings")
async def list_meetings(request: Request) -> list[dict]:
    state = request.app.state.drflash
    return await state.meetings.list_meetings()


@router.get("/meetings/{meeting_id}")
async def get_meeting(meeting_id: str, request: Request) -> dict:
    state = request.app.state.drflash
    meeting = await state.meetings.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@router.post("/meetings/{meeting_id}/transcribe")
async def transcribe_meeting(meeting_id: str, request: Request) -> dict:
    state = request.app.state.drflash
    return await state.meetings.transcribe_meeting(meeting_id)


@router.post("/meetings/{meeting_id}/summarize")
async def summarize_meeting(meeting_id: str, request: Request) -> dict:
    state = request.app.state.drflash
    return await state.meetings.summarize_meeting(meeting_id)


@router.delete("/meetings/{meeting_id}")
async def delete_meeting(meeting_id: str, request: Request) -> dict:
    state = request.app.state.drflash
    deleted = await state.meetings.delete_meeting(meeting_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {"deleted": True}


# ─── Screen Reader ───────────────────────────────────────────

@router.post("/screen/capture")
async def capture_screen(request: Request) -> dict:
    state = request.app.state.drflash
    return state.screen.capture_screen()


@router.post("/screen/capture-window")
async def capture_window(request: Request) -> dict:
    state = request.app.state.drflash
    return state.screen.capture_active_window()


@router.post("/screen/read")
async def read_screen(request: Request) -> dict:
    """Capture screen and extract text via OCR."""
    state = request.app.state.drflash
    capture = state.screen.capture_screen()
    text = state.screen.extract_text(capture["path"])
    return {"text": text[:5000], "capture": capture}


@router.get("/screen/last")
async def last_capture(request: Request) -> dict:
    state = request.app.state.drflash
    capture = state.screen.get_last_capture()
    if not capture:
        return {"error": "No capture yet"}
    return capture
