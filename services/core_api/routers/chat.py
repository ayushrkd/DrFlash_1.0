"""Dr. Flash — Chat Endpoints with streaming support."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    conversation_id: str = "default"


class ChatResponse(BaseModel):
    conversation_id: str
    message: str
    metadata: dict = {}


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    """Send a message and get a complete response."""
    state = request.app.state.drflash
    response = await state.chat.chat(body.conversation_id, body.message)
    conv = state.chat.get_or_create_conversation(body.conversation_id)
    last = conv.messages[-1] if conv.messages else None
    return ChatResponse(
        conversation_id=body.conversation_id,
        message=response,
        metadata=last.metadata if last else {},
    )


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request):
    """Stream a response token by token using SSE."""
    state = request.app.state.drflash

    async def event_generator():
        async for token in state.chat.stream_chat(body.conversation_id, body.message):
            yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations")
async def list_conversations(request: Request) -> list[dict]:
    """List all conversations."""
    state = request.app.state.drflash
    return state.chat.list_conversations()


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, request: Request) -> dict:
    """Get full conversation history."""
    state = request.app.state.drflash
    conv = state.chat.get_or_create_conversation(conversation_id)
    return conv.to_dict()


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, request: Request) -> dict:
    """Delete a conversation."""
    state = request.app.state.drflash
    deleted = state.chat.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True}
