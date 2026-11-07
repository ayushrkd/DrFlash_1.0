"""Dr. Flash — System Tray Companion.

Say "Dr. Flash" and it activates, listens, thinks, speaks back.
No browser needed. Like Iron Man's JARVIS.
"""

from __future__ import annotations

import io
import json
import os
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


# ─── Config ─────────────────────────────────────────────────

API_URL = "http://127.0.0.1:7827"
WAKE_PHRASES = ["dr flash", "doctor flash", "dr. flash", "hey flash", "flash"]
HOTKEY = "ctrl+alt+d"
SAMPLE_RATE = 16000
CHANNELS = 1
CONVERSATION_ID = "companion"

# Wake word detection params (short clips, Vosk, fast)
WAKE_CLIP_SECONDS = 2.5
WAKE_ENERGY_THRESHOLD = 200  # Low threshold to catch speech

# Command recording params (longer, patient, accurate)
COMMAND_SILENCE_THRESHOLD = 300
COMMAND_SILENCE_DURATION = 2.0     # 2 seconds of silence = end of command
COMMAND_MAX_SECONDS = 30           # Max 30 seconds per command


# ─── State ───────────────────────────────────────────────────

class State:
    def __init__(self):
        self.running = True
        self.processing = False
        self.speaking = False
        self.wake_listening = True
        self.icon = None

state = State()


# ─── Icon ────────────────────────────────────────────────────

def make_icon(color=(59, 130, 246)) -> Image.Image:
    icon_path = Path(__file__).parent / "assets" / "icon-64.png"
    if icon_path.exists():
        try:
            return Image.open(icon_path).convert("RGBA").resize((64, 64))
        except Exception:
            pass
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=(20, 20, 30, 240))
    d.polygon([(32, 8), (18, 32), (28, 32), (24, 56), (46, 28), (34, 28), (38, 8)], fill=(*color, 255))
    return img

def set_icon_color(r, g, b):
    if state.icon:
        state.icon.icon = make_icon((r, g, b))


# ─── Audio ───────────────────────────────────────────────────

def record_command() -> np.ndarray | None:
    """Record speech until user stops talking (2s silence)."""
    print("  🎤 Listening for your command...")
    set_icon_color(34, 197, 94)  # green

    chunks = []
    silence_start = None
    active = True

    def cb(indata, frames, t, status):
        nonlocal silence_start, active
        chunks.append(indata.copy())
        rms = np.sqrt(np.mean(indata ** 2)) * 32768
        if rms < COMMAND_SILENCE_THRESHOLD:
            if silence_start is None:
                silence_start = time.time()
            elif time.time() - silence_start > COMMAND_SILENCE_DURATION:
                active = False
        else:
            silence_start = None

    t0 = time.time()
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32",
                        blocksize=int(SAMPLE_RATE * 0.1), callback=cb):
        while active and (time.time() - t0) < COMMAND_MAX_SECONDS:
            time.sleep(0.05)

    if not chunks:
        return None

    audio = np.concatenate(chunks)
    # Skip if too short (< 0.5 seconds of actual sound)
    if len(audio) < SAMPLE_RATE * 0.5:
        return None

    return (audio * 32767).astype(np.int16)


def audio_to_wav(audio: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()


# ─── Transcription ───────────────────────────────────────────

_vosk_model = None

def _get_vosk():
    global _vosk_model
    if _vosk_model is None:
        try:
            from vosk import Model, SetLogLevel
            SetLogLevel(-1)
            p = str(Path(__file__).parent / "data" / "models" / "vosk-small")
            if Path(p).exists():
                _vosk_model = Model(p)
        except Exception:
            pass
    return _vosk_model


def transcribe_vosk(audio_int16: np.ndarray) -> str:
    """Fast offline transcription with Vosk (for wake word detection)."""
    from vosk import KaldiRecognizer
    model = _get_vosk()
    if not model:
        return ""
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    data = audio_int16.tobytes()
    for i in range(0, len(data), 4000):
        rec.AcceptWaveform(data[i:i+4000])
    result = json.loads(rec.FinalResult())
    return result.get("text", "")


def transcribe_google(audio_int16: np.ndarray) -> str:
    """Accurate transcription with Google Speech (for commands)."""
    try:
        import speech_recognition as sr
        wav = audio_to_wav(audio_int16)
        recognizer = sr.Recognizer()
        audio_data = sr.AudioData(wav[44:], SAMPLE_RATE, 2)
        return recognizer.recognize_google(audio_data)
    except Exception as e:
        print(f"  ⚠ Google STT failed: {e}")
        # Fallback to Vosk
        return transcribe_vosk(audio_int16)


# ─── Wake Word ───────────────────────────────────────────────

def detect_wake() -> bool:
    """Listen for 2.5s, check if wake word is spoken."""
    if state.processing or state.speaking:
        return False
    try:
        audio = sd.rec(int(SAMPLE_RATE * WAKE_CLIP_SECONDS), samplerate=SAMPLE_RATE,
                       channels=CHANNELS, dtype="float32")
        sd.wait()

        rms = np.sqrt(np.mean(audio ** 2)) * 32768
        if rms < WAKE_ENERGY_THRESHOLD:
            return False

        audio_int16 = (audio * 32767).astype(np.int16)
        text = transcribe_vosk(audio_int16)
        if not text:
            return False

        for phrase in WAKE_PHRASES:
            if phrase in text.lower():
                print(f"  ⚡ Wake word: '{text}'")
                return True
        return False
    except Exception:
        return False


# ─── API ─────────────────────────────────────────────────────

def send_message(text: str) -> str:
    print(f"  🧠 Thinking: {text}")
    set_icon_color(245, 158, 11)  # orange
    try:
        r = httpx.post(f"{API_URL}/api/v1/chat",
                       json={"message": text, "conversation_id": CONVERSATION_ID},
                       timeout=120.0)
        r.raise_for_status()
        return r.json().get("message", "I couldn't process that.")
    except Exception as e:
        return f"Server error: {str(e)[:80]}"


def speak(text: str):
    """Speak using Windows built-in TTS (always works, no internet needed)."""
    state.speaking = True
    set_icon_color(139, 92, 246)  # purple
    print(f"  🔊 {text[:120]}...")
    try:
        escaped = text.replace("'", "''")[:800]
        subprocess.run(
            ["powershell", "-Command",
             f"Add-Type -AssemblyName System.Speech; "
             f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
             f"$s.Rate = 2; $s.Speak('{escaped}')"],
            timeout=60, capture_output=True,
        )
    except Exception as e:
        print(f"  ⚠ TTS error: {e}")
    state.speaking = False
    set_icon_color(59, 130, 246)  # blue


def acknowledge():
    """Quick acknowledgment — let user know Dr. Flash heard them."""
    speak("Yes?")


# ─── Main Voice Flow ────────────────────────────────────────

def handle_command():
    """Full flow: acknowledge → record → transcribe → think → speak."""
    if state.processing or state.speaking:
        return
    state.processing = True

    try:
        # Step 1: Acknowledge
        acknowledge()

        # Step 2: Record the command (with patience)
        time.sleep(0.3)
        audio = record_command()
        if audio is None or len(audio) < SAMPLE_RATE * 0.3:
            speak("I didn't catch that. Please try again.")
            state.processing = False
            return

        # Step 3: Transcribe with Google (accurate)
        set_icon_color(245, 158, 11)  # orange
        print("  📝 Transcribing...")
        text = transcribe_google(audio)
        if not text:
            speak("Sorry, I couldn't understand. Please try again.")
            state.processing = False
            return

        # Strip wake word from beginning if present
        text_l = text.lower()
        for phrase in WAKE_PHRASES:
            if text_l.startswith(phrase):
                text = text[len(phrase):].strip().lstrip(",.!? ")
                break
        if not text:
            speak("I'm listening. What do you need?")
            state.processing = False
            return

        print(f"  📝 You said: {text}")

        # Step 4: Send to Dr. Flash API
        response = send_message(text)
        print(f"  💬 Response: {response[:200]}")

        # Step 5: Speak the response
        speak(response)

    except Exception as e:
        print(f"  ❌ Error: {e}")
        set_icon_color(239, 68, 68)  # red
        time.sleep(2)
    finally:
        state.processing = False
        set_icon_color(59, 130, 246)  # blue


# ─── Background Threads ─────────────────────────────────────

def wake_loop():
    """Continuously listen for wake word."""
    print("  👂 Listening for 'Dr. Flash'...")
    while state.running:
        if not state.wake_listening or state.processing or state.speaking:
            time.sleep(0.5)
            continue
        try:
            if detect_wake():
                handle_command()
        except Exception:
            time.sleep(1)
        time.sleep(0.3)


def on_hotkey():
    if state.processing or state.speaking:
        return
    print(f"\n  ⌨ Hotkey!")
    threading.Thread(target=handle_command, daemon=True).start()


# ─── Server ──────────────────────────────────────────────────

def check_server() -> bool:
    try:
        return httpx.get(f"{API_URL}/health", timeout=3).status_code == 200
    except Exception:
        return False

def start_server():
    venv_py = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        print("  ⚠ No .venv found")
        return False
    print("  🚀 Starting server...")
    subprocess.Popen([str(venv_py), "run_server.py"],
                     cwd=str(Path(__file__).parent),
                     creationflags=subprocess.CREATE_NO_WINDOW,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        time.sleep(1)
        if check_server():
            print("  ✅ Server running")
            return True
    print("  ⚠ Server failed")
    return False


# ─── Tray ────────────────────────────────────────────────────

def create_tray():
    def on_listen(icon, item):
        threading.Thread(target=handle_command, daemon=True).start()

    def on_wake_toggle(icon, item):
        state.wake_listening = not state.wake_listening
        print(f"  Wake word: {'ON' if state.wake_listening else 'OFF'}")

    def on_chat(icon, item):
        import webbrowser
        webbrowser.open("http://localhost:7828/chat")

    def on_dash(icon, item):
        import webbrowser
        webbrowser.open("http://localhost:7828")

    def on_quit(icon, item):
        state.running = False
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("🎤 Listen Now", on_listen, default=True),
        pystray.MenuItem("👂 Wake Word", on_wake_toggle,
                         checked=lambda item: state.wake_listening),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("💬 Chat", on_chat),
        pystray.MenuItem("📊 Dashboard", on_dash),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ Quit", on_quit),
    )
    icon = pystray.Icon("Dr. Flash", icon=make_icon(),
                        title="Dr. Flash — AI Companion", menu=menu)
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

    if not check_server():
        if not start_server():
            print("  ⚠ Start server manually: .venv\\Scripts\\python run_server.py")
    else:
        print("  ✅ Server running")

    try:
        keyboard.add_hotkey(HOTKEY, on_hotkey)
        print(f"  ✅ Hotkey {HOTKEY.upper()} registered")
    except Exception as e:
        print(f"  ⚠ Hotkey failed: {e}")

    # Pre-load Vosk model
    print("  Loading speech model...")
    _get_vosk()
    print("  ✅ Ready")

    wake_thread = threading.Thread(target=wake_loop, daemon=True)
    wake_thread.start()

    print(f"\n  Say 'Dr. Flash' or press Ctrl+Alt+D\n")

    icon = create_tray()
    icon.run()

    state.running = False
    keyboard.unhook_all()
    print("\n  Dr. Flash stopped.")


if __name__ == "__main__":
    main()
