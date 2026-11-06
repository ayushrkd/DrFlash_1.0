"""JARVIS — Voice Engine.

Local-first voice with:
- TTS via edge-tts (high-quality Microsoft neural voices, free)
- ASR handled by the browser's Web Speech API (zero-latency, private)
- WebSocket for real-time bidirectional voice communication
- Voice state machine: OFF → IDLE → LISTENING → PROCESSING → SPEAKING → IDLE

Privacy: No cloud audio streaming while idle. The browser's Speech API
runs locally in Chromium. TTS synthesis uses edge-tts which connects
briefly to synthesize, then audio is played locally.
"""

from __future__ import annotations

import asyncio
import io
import json
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

import edge_tts


class VoiceState(StrEnum):
    OFF = "OFF"
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


# Good English voices from edge-tts
VOICES = {
    "default": "en-US-GuyNeural",
    "male": "en-US-GuyNeural",
    "female": "en-US-AriaNeural",
    "british_male": "en-GB-RyanNeural",
    "british_female": "en-GB-SoniaNeural",
    "indian_male": "en-IN-PrabhatNeural",
    "indian_female": "en-IN-NeerjaNeural",
}


class VoiceConfig:
    """Voice engine configuration."""

    def __init__(self) -> None:
        self.enabled: bool = False
        self.voice: str = VOICES["default"]
        self.rate: str = "+10%"       # Speech rate adjustment
        self.volume: str = "+0%"
        self.pitch: str = "+0Hz"
        self.wake_word: str = "jarvis"
        self.auto_listen: bool = True  # Auto-listen after speaking
        self.silence_timeout_ms: int = 2000

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "voice": self.voice,
            "rate": self.rate,
            "volume": self.volume,
            "pitch": self.pitch,
            "wake_word": self.wake_word,
            "auto_listen": self.auto_listen,
            "silence_timeout_ms": self.silence_timeout_ms,
            "available_voices": VOICES,
        }


class TTSEngine:
    """Text-to-speech using edge-tts (Microsoft neural voices)."""

    def __init__(self, config: VoiceConfig) -> None:
        self._config = config

    async def synthesize(self, text: str) -> bytes:
        """Synthesize text to MP3 audio bytes. Retries on transient failures."""
        import ssl
        import certifi

        for attempt in range(3):
            try:
                communicate = edge_tts.Communicate(
                    text,
                    voice=self._config.voice,
                    rate=self._config.rate,
                    volume=self._config.volume,
                    pitch=self._config.pitch,
                )
                audio_data = b""
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_data += chunk["data"]
                return audio_data
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(1.0 * (attempt + 1))

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """Stream audio chunks as they're synthesized."""
        communicate = edge_tts.Communicate(
            text,
            voice=self._config.voice,
            rate=self._config.rate,
            volume=self._config.volume,
            pitch=self._config.pitch,
        )
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]

    async def list_voices(self, language: str = "en") -> list[dict]:
        """List available voices for a language."""
        voices = await edge_tts.list_voices()
        return [
            {"name": v["ShortName"], "gender": v["Gender"], "locale": v["Locale"]}
            for v in voices
            if v["Locale"].startswith(language)
        ]


class VoiceEngine:
    """Central voice engine managing state, TTS, and voice sessions."""

    def __init__(self) -> None:
        self.config = VoiceConfig()
        self.tts = TTSEngine(self.config)
        self._state = VoiceState.OFF
        self._active_sessions: dict[str, dict] = {}
        self._history: list[dict] = []

    @property
    def state(self) -> VoiceState:
        return self._state

    def set_state(self, new_state: VoiceState) -> None:
        old = self._state
        self._state = new_state
        self._history.append({
            "from": old, "to": new_state,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def enable(self) -> None:
        self.config.enabled = True
        self.set_state(VoiceState.IDLE)

    def disable(self) -> None:
        self.config.enabled = False
        self.set_state(VoiceState.OFF)

    async def speak(self, text: str) -> bytes:
        """Synthesize speech and return audio bytes."""
        self.set_state(VoiceState.SPEAKING)
        try:
            audio = await self.tts.synthesize(text)
            return audio
        finally:
            if self.config.enabled:
                self.set_state(VoiceState.IDLE)
            else:
                self.set_state(VoiceState.OFF)

    async def speak_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """Stream synthesized speech chunks."""
        self.set_state(VoiceState.SPEAKING)
        try:
            async for chunk in self.tts.synthesize_stream(text):
                yield chunk
        finally:
            if self.config.enabled:
                self.set_state(VoiceState.IDLE)
            else:
                self.set_state(VoiceState.OFF)

    def status(self) -> dict:
        return {
            "state": self._state.value,
            "enabled": self.config.enabled,
            "voice": self.config.voice,
            "active_sessions": len(self._active_sessions),
            "config": self.config.to_dict(),
        }
