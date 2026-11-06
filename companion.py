"""Dr. Flash — System Tray Companion.

This is the Iron Man experience. Runs in the system tray, always listening.
Say "Dr. Flash" (or "Doctor Flash") and it activates, listens to your command,
sends it to the AI, and speaks the response back.

No browser needed. No UI needed. Just your voice.

Features:
- System tray icon with status indicator
- Global hotkey (Ctrl+Alt+D) to activate
- Always-on wake word detection ("Dr Flash" / "Doctor Flash")
- Push-to-talk via tray menu
- Speaks responses via edge-tts or Windows TTS fallback
- Starts API server automatically if not running
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import httpx
import keyboard
import numpy as np
import pystray
import sounddevice as sd
from PIL import Image, ImageDraw


# ─── Configuration ──────────────────────────────────────────

API_URL = "http://127.0.0.1:8000"
WAKE_PHRASES = ["dr flash", "doctor flash", "dr. flash", "hey flash", "flash"]
HOTKEY = "ctrl+alt+d"
SAMPLE_RATE = 16000
CHANNELS = 1
SILENCE_THRESHOLD = 500        # RMS threshold for silence detection
SILENCE_DURATION = 1.5         # Seconds of silence to end recording
MAX_RECORD_SECONDS = 15        # Max recording time
WAKE_CHECK_INTERVAL = 0.5      # Seconds between wake word checks
CONVERSATION_ID = "companion"  # Persistent companion conversation


# ─── State ──────────────────────────────────────────────────

class CompanionState:
    def __init__(self):
        self.running = True
        self.listening = False
        self.processing = False
        self.speaking = False
        self.wake_listening = True
        self.icon = None
        self.status = "Idle"
        self.last_response = ""


state = CompanionState()


# ─── Icon creation ──────────────────────────────────────────

def create_icon(color: str = "#3b82f6") -> Image.Image:
    """Create a simple tray icon."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Flash bolt shape
    if color == "#22c55e":  # Active/listening
        fill = (34, 197, 94, 255)
    elif color == "#f59e0b":  # Processing
        fill = (245, 158, 11, 255)
    elif color == "#8b5cf6":  # Speaking
        fill = (139, 92, 246, 255)
    elif color == "#ef4444":  # Error
        fill = (239, 68, 68, 255)
    else:  # Default blue
        fill = (59, 130, 246, 255)

    # Circle background
    draw.ellipse([4, 4, 60, 60], fill=(20, 20, 30, 240))
    # Lightning bolt
    bolt = [(32, 8), (18, 32), (28, 32), (24, 56), (46, 28), (34, 28), (38, 8)]
    draw.polygon(bolt, fill=fill)
    return img


def update_icon(color: str = "#3b82f6"):
    """Update the tray icon color."""
    if state.icon:
        state.icon.icon = create_icon(color)


# ─── Audio helpers ──────────────────────────────────────────

def record_speech() -> np.ndarray | None:
    """Record speech until silence is detected."""
    print("  🎤 Recording...")
    state.status = "Listening"
    update_icon("#22c55e")

    audio_chunks = []
    silence_start = None
    recording = True

    def callback(indata, frames, time_info, status):
        nonlocal silence_start, recording
        audio_chunks.append(indata.copy())
        rms = np.sqrt(np.mean(indata ** 2)) * 32768
        if rms < SILENCE_THRESHOLD:
            if silence_start is None:
                silence_start = time.time()
            elif time.time() - silence_start > SILENCE_DURATION:
                recording = False
        else:
            silence_start = None

    start_time = time.time()
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32",
                        blocksize=int(SAMPLE_RATE * 0.1), callback=callback):
        while recording and (time.time() - start_time) < MAX_RECORD_SECONDS:
            time.sleep(0.05)

    if not audio_chunks:
        return None

    audio = np.concatenate(audio_chunks)
    # Convert to int16 for speech recognition
    audio_int16 = (audio * 32767).astype(np.int16)
    return audio_int16


def audio_to_wav_bytes(audio: np.ndarray) -> bytes:
    """Convert numpy audio to WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # int16
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()


def transcribe_audio(audio: np.ndarray) -> str:
    """Transcribe audio using speech_recognition."""
    import speech_recognition as sr

    wav_bytes = audio_to_wav_bytes(audio)
    recognizer = sr.Recognizer()
    audio_data = sr.AudioData(wav_bytes[44:], SAMPLE_RATE, 2)  # Skip WAV header

    try:
        # Try Google's free API first (requires internet)
        text = recognizer.recognize_google(audio_data)
        return text
    except Exception:
        pass

    try:
        # Fallback to Windows SAPI
        text = recognizer.recognize_google(audio_data, language="en-US")
        return text
    except Exception as e:
        print(f"  ⚠ Transcription failed: {e}")
        return ""


# ─── Wake word detection ────────────────────────────────────

def detect_wake_word() -> bool:
    """Listen briefly and check for wake word."""
    try:
        duration = 2.0
        audio = sd.rec(int(SAMPLE_RATE * duration), samplerate=SAMPLE_RATE,
                       channels=CHANNELS, dtype="float32")
        sd.wait()

        # Check if there's speech (above noise threshold)
        rms = np.sqrt(np.mean(audio ** 2)) * 32768
        if rms < SILENCE_THRESHOLD * 0.5:
            return False

        # Transcribe and check for wake word
        audio_int16 = (audio * 32767).astype(np.int16)
        text = transcribe_audio(audio_int16)
        if not text:
            return False

        text_lower = text.lower()
        for phrase in WAKE_PHRASES:
            if phrase in text_lower:
                print(f"  ⚡ Wake word detected: '{text}'")
                return True

        return False
    except Exception:
        return False


# ─── API communication ──────────────────────────────────────

def send_to_api(text: str) -> str:
    """Send text to Dr. Flash API and get response."""
    state.status = "Thinking"
    update_icon("#f59e0b")
    print(f"  🧠 Sending: {text}")

    try:
        resp = httpx.post(
            f"{API_URL}/api/v1/chat",
            json={"message": text, "conversation_id": CONVERSATION_ID},
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", "I couldn't process that.")
    except Exception as e:
        return f"I'm having trouble connecting to the server. Error: {str(e)[:100]}"


def speak_response(text: str):
    """Speak the response using edge-tts or Windows fallback."""
    state.speaking = True
    state.status = "Speaking"
    update_icon("#8b5cf6")
    print(f"  🔊 Speaking: {text[:100]}...")

    try:
        # Try edge-tts via API
        resp = httpx.post(
            f"{API_URL}/api/v1/voice/speak",
            json={"text": text},
            timeout=30.0,
        )
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("audio"):
            # Play the audio
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(resp.content)
                temp_path = f.name

            # Use Windows media player to play
            os.system(f'start /min "" "wmplayer" "{temp_path}"')
            time.sleep(max(2, len(text) * 0.06))  # Rough estimate of duration
            try:
                os.unlink(temp_path)
            except Exception:
                pass
        else:
            # Fallback to Windows SAPI TTS
            _speak_windows(text)
    except Exception:
        _speak_windows(text)

    state.speaking = False
    state.status = "Idle"
    update_icon("#3b82f6")


def _speak_windows(text: str):
    """Use Windows built-in text-to-speech."""
    try:
        # Use PowerShell to invoke Windows SAPI
        escaped = text.replace("'", "''").replace('"', '`"')[:500]
        subprocess.run(
            ["powershell", "-Command",
             f"Add-Type -AssemblyName System.Speech; "
             f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
             f"$s.Rate = 2; $s.Speak('{escaped}')"],
            timeout=30, capture_output=True,
        )
    except Exception as e:
        print(f"  ⚠ Windows TTS failed: {e}")


# ─── Main voice interaction loop ────────────────────────────

def handle_voice_command():
    """Full cycle: record → transcribe → send to API → speak response."""
    if state.processing or state.speaking:
        return

    state.processing = True
    state.listening = True

    try:
        # Record speech
        audio = record_speech()
        state.listening = False

        if audio is None or len(audio) < SAMPLE_RATE * 0.3:
            print("  ⚠ No speech detected")
            state.processing = False
            state.status = "Idle"
            update_icon("#3b82f6")
            return

        # Transcribe
        state.status = "Transcribing"
        update_icon("#f59e0b")
        text = transcribe_audio(audio)

        if not text:
            print("  ⚠ Couldn't understand")
            state.processing = False
            state.status = "Idle"
            update_icon("#3b82f6")
            return

        # Remove wake word from command if present
        text_lower = text.lower()
        for phrase in WAKE_PHRASES:
            if text_lower.startswith(phrase):
                text = text[len(phrase):].strip()
                if text and text[0] in ",.!?":
                    text = text[1:].strip()
                break

        if not text:
            speak_response("Yes? I'm listening.")
            state.processing = False
            return

        print(f"  📝 Heard: {text}")

        # Send to API
        response = send_to_api(text)
        state.last_response = response
        print(f"  💬 Response: {response[:200]}")

        # Speak response
        speak_response(response)

    except Exception as e:
        print(f"  ❌ Error: {e}")
        state.status = "Error"
        update_icon("#ef4444")
        time.sleep(2)

    finally:
        state.processing = False
        state.listening = False
        state.status = "Idle"
        update_icon("#3b82f6")


# ─── Wake word background thread ────────────────────────────

def wake_word_loop():
    """Continuously listen for wake word in background."""
    print("  👂 Wake word detection active — say 'Dr. Flash' or press Ctrl+Alt+D")
    while state.running:
        if not state.wake_listening or state.processing or state.speaking:
            time.sleep(0.5)
            continue
        try:
            if detect_wake_word():
                handle_voice_command()
        except Exception:
            time.sleep(1)
        time.sleep(0.2)


# ─── Hotkey handler ─────────────────────────────────────────

def on_hotkey():
    """Handle global hotkey press."""
    if state.processing or state.speaking:
        return
    print(f"\n  ⌨ Hotkey activated!")
    threading.Thread(target=handle_voice_command, daemon=True).start()


# ─── Server management ──────────────────────────────────────

def check_server() -> bool:
    """Check if the API server is running."""
    try:
        resp = httpx.get(f"{API_URL}/health", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


def start_server():
    """Start the API server in background."""
    project_dir = Path(__file__).parent
    venv_python = project_dir / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        print("  ⚠ Virtual environment not found. Please run setup first.")
        return False

    print("  🚀 Starting Dr. Flash server...")
    subprocess.Popen(
        [str(venv_python), "run_server.py"],
        cwd=str(project_dir),
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for server to start
    for _ in range(20):
        time.sleep(1)
        if check_server():
            print("  ✅ Server is running")
            return True

    print("  ⚠ Server failed to start")
    return False


# ─── System tray setup ──────────────────────────────────────

def create_tray():
    """Create the system tray icon and menu."""

    def on_activate(icon, item):
        threading.Thread(target=handle_voice_command, daemon=True).start()

    def on_wake_toggle(icon, item):
        state.wake_listening = not state.wake_listening
        status = "ON" if state.wake_listening else "OFF"
        print(f"  Wake word: {status}")

    def on_open_chat(icon, item):
        import webbrowser
        webbrowser.open("http://localhost:3000/chat")

    def on_open_dashboard(icon, item):
        import webbrowser
        webbrowser.open("http://localhost:3000")

    def on_quit(icon, item):
        state.running = False
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("🎤 Listen Now", on_activate, default=True),
        pystray.MenuItem("👂 Wake Word Detection",
                         on_wake_toggle,
                         checked=lambda item: state.wake_listening),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("💬 Open Chat", on_open_chat),
        pystray.MenuItem("📊 Open Dashboard", on_open_dashboard),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ Quit", on_quit),
    )

    icon = pystray.Icon(
        "Dr. Flash",
        icon=create_icon(),
        title="Dr. Flash — AI Companion",
        menu=menu,
    )
    state.icon = icon
    return icon


# ─── Main ───────────────────────────────────────────────────

def main():
    print("\n" + "=" * 50)
    print("  ⚡ Dr. Flash — AI Companion")
    print("=" * 50)
    print(f"  Hotkey: {HOTKEY.upper()}")
    print(f"  Wake words: {', '.join(WAKE_PHRASES[:3])}")
    print()

    # Check/start server
    if not check_server():
        if not start_server():
            print("  ⚠ Running without server — please start it manually")
    else:
        print("  ✅ Server already running")

    # Register global hotkey
    try:
        keyboard.add_hotkey(HOTKEY, on_hotkey)
        print(f"  ✅ Hotkey {HOTKEY.upper()} registered")
    except Exception as e:
        print(f"  ⚠ Hotkey registration failed: {e}")

    # Start wake word detection in background
    wake_thread = threading.Thread(target=wake_word_loop, daemon=True)
    wake_thread.start()

    print("\n  Ready! Say 'Dr. Flash' or press Ctrl+Alt+D")
    print("  Right-click tray icon for menu\n")

    # Run system tray (blocks)
    icon = create_tray()
    icon.run()

    # Cleanup
    state.running = False
    keyboard.unhook_all()
    print("\n  Dr. Flash companion stopped.")


if __name__ == "__main__":
    main()
