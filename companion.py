"""Dr. Flash — System Tray Companion.

Say "Dr. Flash" and it wakes up. No browser needed.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
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


# ─── Config ──────────────────────────────────────────────────

API_URL = "http://127.0.0.1:7827"
WAKE_PHRASES = ["dr flash", "doctor flash", "hey flash", "flash"]
HOTKEY = "ctrl+alt+d"
SAMPLE_RATE = 16000
CHANNELS = 1
CONVERSATION_ID = "companion"

# Tuning
WAKE_CLIP_SECONDS = 2.5
WAKE_ENERGY_THRESHOLD = 150      # catch even soft speech
COMMAND_SILENCE_THRESHOLD = 250  # end of speech detection
COMMAND_SILENCE_SECONDS = 2.0    # 2s silence = done talking
COMMAND_MAX_SECONDS = 30


# ─── State ───────────────────────────────────────────────────

class S:
    running = True
    busy = False       # True when processing a command (record/think/speak)
    wake_on = True
    icon = None

state = S()


# ─── Vosk Model (loaded once) ───────────────────────────────

_vosk_model = None

def load_vosk():
    global _vosk_model
    if _vosk_model is not None:
        return _vosk_model
    try:
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        model_path = str(Path(__file__).parent / "data" / "models" / "vosk-small")
        if Path(model_path).exists():
            _vosk_model = Model(model_path)
            return _vosk_model
    except Exception as e:
        print(f"  ⚠ Vosk load failed: {e}")
    return None


def vosk_transcribe(audio_int16: np.ndarray) -> str:
    """Transcribe with Vosk (offline, fast)."""
    from vosk import KaldiRecognizer
    model = load_vosk()
    if not model:
        return ""
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    raw = audio_int16.tobytes()
    for i in range(0, len(raw), 4000):
        rec.AcceptWaveform(raw[i:i+4000])
    return json.loads(rec.FinalResult()).get("text", "")


# ─── Icon ────────────────────────────────────────────────────

def mk_icon(r=59, g=130, b=246):
    p = Path(__file__).parent / "assets" / "icon-64.png"
    if p.exists():
        try:
            return Image.open(p).convert("RGBA").resize((64, 64))
        except Exception:
            pass
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=(20, 20, 30, 240))
    d.polygon([(32, 8), (18, 32), (28, 32), (24, 56), (46, 28), (34, 28), (38, 8)], fill=(r, g, b, 255))
    return img

def icon_color(r, g, b):
    if state.icon:
        try:
            state.icon.icon = mk_icon(r, g, b)
        except Exception:
            pass


# ─── Audio Recording ─────────────────────────────────────────

def record_command() -> np.ndarray | None:
    """Record until 2s of silence or 30s max."""
    icon_color(34, 197, 94)  # green = listening
    chunks = []
    silence_t = None
    go = True

    def cb(data, frames, ti, st):
        nonlocal silence_t, go
        chunks.append(data.copy())
        rms = np.sqrt(np.mean(data ** 2)) * 32768
        if rms < COMMAND_SILENCE_THRESHOLD:
            if silence_t is None:
                silence_t = time.time()
            elif time.time() - silence_t > COMMAND_SILENCE_SECONDS:
                go = False
        else:
            silence_t = None

    t0 = time.time()
    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32",
                            blocksize=int(SAMPLE_RATE * 0.1), callback=cb):
            while go and (time.time() - t0) < COMMAND_MAX_SECONDS:
                time.sleep(0.05)
    except Exception as e:
        print(f"  ⚠ Mic error: {e}")
        return None

    if not chunks or len(chunks) < 3:
        return None
    audio = np.concatenate(chunks)
    if len(audio) < SAMPLE_RATE * 0.4:
        return None
    return (audio * 32767).astype(np.int16)


# ─── TTS (Windows built-in, always works) ────────────────────

def speak(text: str):
    state.busy = True
    icon_color(139, 92, 246)  # purple = speaking
    short = text[:150].replace("\n", " ")
    print(f"  🔊 {short}{'...' if len(text) > 150 else ''}")
    try:
        # Escape for PowerShell
        clean = text.replace("'", "''").replace('"', "'").replace("\n", " ")[:1000]
        subprocess.run(
            ["powershell", "-Command",
             f"Add-Type -AssemblyName System.Speech;"
             f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
             f"$s.Rate = 1; $s.Speak('{clean}')"],
            timeout=60, capture_output=True,
        )
    except Exception as e:
        print(f"  ⚠ TTS: {e}")
    icon_color(59, 130, 246)  # blue = idle


# ─── API Call ─────────────────────────────────────────────────

def ask_drflash(text: str) -> str:
    icon_color(245, 158, 11)  # orange = thinking
    print(f"  🧠 → {text}")
    try:
        r = httpx.post(f"{API_URL}/api/v1/chat",
                       json={"message": text, "conversation_id": CONVERSATION_ID},
                       timeout=120.0)
        r.raise_for_status()
        return r.json().get("message", "Hmm, something went wrong.")
    except Exception as e:
        return f"Can't reach the server. Make sure it's running. ({str(e)[:60]})"


# ─── Voice Command Flow ──────────────────────────────────────

def handle_command():
    """Wake → 'Yes?' → Record → Transcribe → Think → Speak."""
    if state.busy:
        return
    state.busy = True

    try:
        # 1. Acknowledge
        speak("Yes?")

        # 2. Record
        print("  🎤 Listening...")
        time.sleep(0.2)
        audio = record_command()
        if audio is None:
            speak("Didn't catch that. Try again.")
            return

        # 3. Transcribe (Vosk — offline, always works)
        icon_color(245, 158, 11)  # orange
        print("  📝 Transcribing...")
        text = vosk_transcribe(audio)

        if not text or len(text.strip()) < 2:
            speak("Sorry, couldn't make that out.")
            return

        # Strip wake word from start
        t = text.lower()
        for w in WAKE_PHRASES:
            if t.startswith(w):
                text = text[len(w):].strip().lstrip(",.!? ")
                break
        if not text:
            speak("I'm here. What do you need?")
            return

        print(f"  📝 Heard: '{text}'")

        # 4. Think (API)
        response = ask_drflash(text)

        # 5. Speak
        speak(response)

    except Exception as e:
        print(f"  ❌ {e}")
        icon_color(239, 68, 68)
        time.sleep(1)
    finally:
        state.busy = False
        icon_color(59, 130, 246)


# ─── Wake Word Loop ──────────────────────────────────────────

def wake_loop():
    print("  👂 Listening for 'Dr. Flash'...")
    while state.running:
        if not state.wake_on or state.busy:
            time.sleep(0.5)
            continue

        try:
            # Record short clip
            audio = sd.rec(int(SAMPLE_RATE * WAKE_CLIP_SECONDS),
                           samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32")
            sd.wait()

            # Check energy
            rms = np.sqrt(np.mean(audio ** 2)) * 32768
            if rms < WAKE_ENERGY_THRESHOLD:
                continue

            # Check for wake word
            audio_int16 = (audio * 32767).astype(np.int16)
            text = vosk_transcribe(audio_int16)
            if not text:
                continue

            for phrase in WAKE_PHRASES:
                if phrase in text.lower():
                    print(f"  ⚡ Wake: '{text}'")
                    handle_command()
                    break

        except Exception:
            time.sleep(0.5)

        time.sleep(0.2)  # Brief pause between checks


def on_hotkey():
    if state.busy:
        return
    print(f"\n  ⌨ Hotkey!")
    threading.Thread(target=handle_command, daemon=True).start()


# ─── Server Check ────────────────────────────────────────────

def server_ok() -> bool:
    try:
        return httpx.get(f"{API_URL}/health", timeout=3).status_code == 200
    except Exception:
        return False

def start_server():
    py = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        return False
    print("  🚀 Starting server...")
    subprocess.Popen([str(py), "run_server.py"], cwd=str(Path(__file__).parent),
                     creationflags=subprocess.CREATE_NO_WINDOW,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        time.sleep(1)
        if server_ok():
            print("  ✅ Server up")
            return True
    return False


# ─── Tray ────────────────────────────────────────────────────

def build_tray():
    def on_listen(i, it):
        threading.Thread(target=handle_command, daemon=True).start()
    def on_toggle_wake(i, it):
        state.wake_on = not state.wake_on
        print(f"  Wake: {'ON' if state.wake_on else 'OFF'}")
    def on_chat(i, it):
        import webbrowser; webbrowser.open("http://localhost:7828/chat")
    def on_dash(i, it):
        import webbrowser; webbrowser.open("http://localhost:7828")
    def on_quit(i, it):
        state.running = False; i.stop()

    menu = pystray.Menu(
        pystray.MenuItem("🎤 Listen Now", on_listen, default=True),
        pystray.MenuItem("👂 Wake Word", on_toggle_wake, checked=lambda it: state.wake_on),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("💬 Chat", on_chat),
        pystray.MenuItem("📊 Dashboard", on_dash),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ Quit", on_quit),
    )
    icon = pystray.Icon("Dr. Flash", icon=mk_icon(), title="⚡ Dr. Flash", menu=menu)
    state.icon = icon
    return icon


# ─── Main ────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 50)
    print("  ⚡ Dr. Flash — AI Companion")
    print("=" * 50)

    if not server_ok():
        if not start_server():
            print("  ⚠ Run server manually first")
    else:
        print("  ✅ Server running")

    try:
        keyboard.add_hotkey(HOTKEY, on_hotkey)
        print(f"  ✅ Hotkey: {HOTKEY.upper()}")
    except Exception:
        pass

    print("  Loading Vosk...")
    load_vosk()
    print("  ✅ Speech model loaded")

    t = threading.Thread(target=wake_loop, daemon=True)
    t.start()

    print(f"\n  Say 'Dr. Flash' or press Ctrl+Alt+D\n")
    build_tray().run()
    state.running = False
    print("\n  Stopped.")


if __name__ == "__main__":
    main()
