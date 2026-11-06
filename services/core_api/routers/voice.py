"""Dr. Flash — Voice API Endpoints.

REST endpoints for TTS, voice configuration, and status.
WebSocket for real-time voice sessions.
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from services.voice import VoiceState

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


class SpeakRequest(BaseModel):
    text: str
    voice: str | None = None


class VoiceConfigUpdate(BaseModel):
    enabled: bool | None = None
    voice: str | None = None
    rate: str | None = None
    wake_word: str | None = None
    auto_listen: bool | None = None


@router.get("/status")
async def voice_status(request: Request) -> dict:
    """Get voice engine status."""
    engine = request.app.state.drflash.voice
    return engine.status()


@router.post("/enable")
async def enable_voice(request: Request) -> dict:
    """Enable voice engine."""
    engine = request.app.state.drflash.voice
    engine.enable()
    return engine.status()


@router.post("/disable")
async def disable_voice(request: Request) -> dict:
    """Disable voice engine."""
    engine = request.app.state.drflash.voice
    engine.disable()
    return engine.status()


@router.post("/config")
async def update_config(body: VoiceConfigUpdate, request: Request) -> dict:
    """Update voice configuration."""
    engine = request.app.state.drflash.voice
    if body.enabled is not None:
        if body.enabled:
            engine.enable()
        else:
            engine.disable()
    if body.voice is not None:
        engine.config.voice = body.voice
    if body.rate is not None:
        engine.config.rate = body.rate
    if body.wake_word is not None:
        engine.config.wake_word = body.wake_word
    if body.auto_listen is not None:
        engine.config.auto_listen = body.auto_listen
    return engine.status()


@router.post("/speak")
async def speak(body: SpeakRequest, request: Request):
    """Synthesize text to speech, return MP3 audio. Falls back to signal browser TTS."""
    engine = request.app.state.drflash.voice
    if body.voice:
        engine.config.voice = body.voice

    try:
        audio_data = await engine.speak(body.text)
        return Response(
            content=audio_data,
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline"},
        )
    except Exception as e:
        # Signal frontend to use browser TTS fallback
        return Response(
            content=json.dumps({"fallback": "browser_tts", "text": body.text, "error": str(e)[:100]}),
            media_type="application/json",
            status_code=200,
            headers={"X-TTS-Fallback": "browser"},
        )


@router.post("/speak/stream")
async def speak_stream(body: SpeakRequest, request: Request):
    """Stream TTS audio as it's synthesized."""
    engine = request.app.state.drflash.voice

    async def generate():
        async for chunk in engine.speak_stream(body.text):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline"},
    )


@router.get("/voices")
async def list_voices(request: Request, language: str = "en") -> list[dict]:
    """List available TTS voices."""
    engine = request.app.state.drflash.voice
    return await engine.tts.list_voices(language)


@router.websocket("/ws")
async def voice_websocket(websocket: WebSocket):
    """WebSocket for real-time voice sessions.

    Protocol:
    Client sends: { "type": "transcript", "text": "...", "final": true }
    Client sends: { "type": "control", "action": "start|stop|cancel" }
    Server sends: { "type": "state", "state": "LISTENING|PROCESSING|SPEAKING|IDLE" }
    Server sends: { "type": "response", "text": "..." }
    Server sends: { "type": "audio_start" }
    Server sends: binary audio chunks
    Server sends: { "type": "audio_end" }
    """
    await websocket.accept()
    app_state = websocket.app.state.drflash
    engine = app_state.voice
    chat = app_state.chat
    session_id = f"voice_{int(time.time() * 1000)}"
    conversation_id = f"voice_{session_id}"

    engine._active_sessions[session_id] = {"started": time.time()}

    try:
        # Enable voice on WebSocket connection
        if not engine.config.enabled:
            engine.enable()

        await websocket.send_json({"type": "state", "state": engine.state.value})
        await websocket.send_json({"type": "config", **engine.config.to_dict()})

        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg["type"] == "transcript":
                text = msg.get("text", "").strip()
                is_final = msg.get("final", False)

                if not text or not is_final:
                    continue

                # Process the transcript
                engine.set_state(VoiceState.PROCESSING)
                await websocket.send_json({"type": "state", "state": "PROCESSING"})

                # Get LLM response via chat service
                try:
                    response_text = await chat.chat(conversation_id, text)
                except Exception as e:
                    response_text = f"I'm sorry, I encountered an error: {str(e)[:100]}"

                await websocket.send_json({
                    "type": "response",
                    "text": response_text,
                    "user_text": text,
                })

                # Stream TTS audio
                engine.set_state(VoiceState.SPEAKING)
                await websocket.send_json({"type": "state", "state": "SPEAKING"})

                try:
                    await websocket.send_json({"type": "audio_start"})
                    async for chunk in engine.tts.synthesize_stream(response_text):
                        await websocket.send_bytes(chunk)
                    await websocket.send_json({"type": "audio_end"})
                except Exception:
                    # Fallback: tell browser to use SpeechSynthesis
                    await websocket.send_json({
                        "type": "speak_browser",
                        "text": response_text,
                    })

                # Return to idle
                engine.set_state(VoiceState.IDLE)
                await websocket.send_json({"type": "state", "state": "IDLE"})

            elif msg["type"] == "control":
                action = msg.get("action")
                if action == "start":
                    engine.set_state(VoiceState.LISTENING)
                    await websocket.send_json({"type": "state", "state": "LISTENING"})
                elif action == "stop":
                    engine.set_state(VoiceState.IDLE)
                    await websocket.send_json({"type": "state", "state": "IDLE"})
                elif action == "cancel":
                    engine.set_state(VoiceState.IDLE)
                    await websocket.send_json({"type": "state", "state": "IDLE"})

            elif msg["type"] == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)[:200]})
        except Exception:
            pass
    finally:
        engine._active_sessions.pop(session_id, None)
        if not engine._active_sessions:
            engine.set_state(VoiceState.IDLE if engine.config.enabled else VoiceState.OFF)
