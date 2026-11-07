"""Dr. Flash — System Tray Companion.

Say "Dr. Flash" and it wakes up. Uses:
- Vosk: wake word detection (fast, offline, low CPU)
- faster-whisper: command transcription (accurate, GPU-accelerated)
- Piper TTS: natural-sounding speech output (offline, neural)
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

import httpx
import keyboard
import numpy as np
import pystray
import sounddevice as sd
import soundfile as sf
from PIL import Image, ImageDraw


# ─── Config ──────────────────────────────────────────────────

API_URL = "http://127.0.0.1:7827"
WAKE_PHRASES = ["dr flash", "doctor flash", "hey flash", "flash"]
HOTKEY = "ctrl+alt+d"
SAMPLE_RATE = 16000
CHANNELS = 1
CONVERSATION_ID = "companion"

WAKE_CLIP_SECONDS = 2.5
WAKE_ENERGY_THRESHOLD = 150
COMMAND_SILENCE_THRESHOLD = 250
COMMAND_SILENCE_SECONDS = 2.0
COMMAND_MAX_SECONDS = 30

PROJECT_DIR = Path(__file__).parent
PIPER_MODEL = str(PROJECT_DIR / "data" / "models" / "piper" / "en_US-lessac-medium.onnx")


# ─── State ───────────────────────────────────────────────────

class S:
    running = True
    busy = False
    wake_on = True
    icon = None

state = S()


# ─── Vosk (wake word only) ──────────────────────────────────

_vosk_model = None

def load_vosk():
    global _vosk_model
    if _vosk_model is not None:
        return _vosk_model
    try:
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        p = str(PROJECT_DIR / "data" / "models" / "vosk-small")
        if Path(p).exists():
            _vosk_model = Model(p)
    except Exception as e:
        print(f"  ⚠ Vosk: {e}")
    return _vosk_model

def vosk_transcribe(audio_int16: np.ndarray) -> str:
    from vosk import KaldiRecognizer
    model = load_vosk()
    if not model:
        return ""
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    raw = audio_int16.tobytes()
    for i in range(0, len(raw), 4000):
        rec.AcceptWaveform(raw[i:i+4000])
    return json.loads(rec.FinalResult()).get("text", "")


# ─── faster-whisper (accurate command transcription) ─────────

_whisper_model = None

def load_whisper():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    try:
        from faster_whisper import WhisperModel
        # Try GPU first with base model (small, fast, downloads quickly)
        # User can change to "large-v3" for better accuracy once downloaded
        print("  Loading Whisper on GPU...")
        _whisper_model = WhisperModel("base", device="cuda", compute_type="float16")
        print("  ✅ Whisper ready (GPU, base)")
    except Exception as e:
        print(f"  ⚠ Whisper GPU failed ({e}), trying CPU...")
        try:
            from faster_whisper import WhisperModel
            _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
            print("  ✅ Whisper ready (CPU, base)")
        except Exception as e2:
            print(f"  ⚠ Whisper failed: {e2}")
    return _whisper_model

def whisper_transcribe(audio_int16: np.ndarray) -> str:
    """Accurate transcription with faster-whisper."""
    model = load_whisper()
    if not model:
        return vosk_transcribe(audio_int16)  # fallback

    audio_f32 = audio_int16.astype(np.float32) / 32768.0
    segments, info = model.transcribe(audio_f32, beam_size=5, language="en")
    text = " ".join(seg.text for seg in segments).strip()
    return text


# ─── Piper TTS (natural offline voice) ──────────────────────

def speak_piper(text: str) -> bool:
    """Speak using Piper TTS. Returns True if successful."""
    if not Path(PIPER_MODEL).exists():
        return False

    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = tmp.name
        tmp.close()

        proc = subprocess.run(
            [str(PROJECT_DIR / ".venv" / "Scripts" / "python.exe"),
             "-m", "piper", "-m", PIPER_MODEL, "-f", tmp_path],
            input=text, capture_output=True, text=True, timeout=30,
            cwd=str(PROJECT_DIR),
        )

        if proc.returncode == 0 and Path(tmp_path).stat().st_size > 100:
            data, sr = sf.read(tmp_path)
            sd.play(data, sr)
            sd.wait()
            os.unlink(tmp_path)
            return True
        else:
            os.unlink(tmp_path)
            return False
    except Exception as e:
        print(f"  ⚠ Piper TTS: {e}")
        return False


def speak_sapi(text: str):
    """Fallback: Windows built-in TTS."""
    try:
        clean = text.replace("'", "''").replace('"', "'").replace("\n", " ")[:1000]
        subprocess.run(
            ["powershell", "-Command",
             f"Add-Type -AssemblyName System.Speech;"
             f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
             f"$s.Rate = 1; $s.Speak('{clean}')"],
            timeout=60, capture_output=True,
        )
    except Exception:
        pass


def speak(text: str):
    """Speak using best available TTS."""
    state.busy = True
    icon_color(139, 92, 246)  # purple
    short = text[:120].replace("\n", " ")
    print(f"  🔊 {short}{'...' if len(text) > 120 else ''}")

    if not speak_piper(text):
        speak_sapi(text)

    icon_color(59, 130, 246)  # blue


# ─── Icon ────────────────────────────────────────────────────

def mk_icon(r=59, g=130, b=246):
    p = PROJECT_DIR / "assets" / "icon-64.png"
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
    icon_color(34, 197, 94)  # green
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
        print(f"  ⚠ Mic: {e}")
        return None

    if not chunks or len(chunks) < 3:
        return None
    audio = np.concatenate(chunks)
    if len(audio) < SAMPLE_RATE * 0.4:
        return None
    return (audio * 32767).astype(np.int16)


# ─── API ─────────────────────────────────────────────────────

def ask_drflash(text: str) -> str:
    icon_color(245, 158, 11)  # orange
    print(f"  🧠 → {text}")
    try:
        r = httpx.post(f"{API_URL}/api/v1/chat",
                       json={"message": text, "conversation_id": CONVERSATION_ID},
                       timeout=120.0)
        r.raise_for_status()
        return r.json().get("message", "Hmm, something went wrong.")
    except Exception as e:
        return f"Can't reach the server. ({str(e)[:60]})"


# ─── Voice Command Flow ──────────────────────────────────────

def handle_command():
    if state.busy:
        return
    state.busy = True

    try:
        speak("Yes?")

        print("  🎤 Listening...")
        time.sleep(0.2)
        audio = record_command()
        if audio is None:
            speak("Didn't catch that. Try again.")
            return

        # Transcribe with faster-whisper (accurate)
        icon_color(245, 158, 11)
        print("  📝 Transcribing with Whisper...")
        text = whisper_transcribe(audio)

        if not text or len(text.strip()) < 2:
            speak("Sorry, couldn't make that out.")
            return

        # Strip wake word
        t = text.lower()
        for w in WAKE_PHRASES:
            if t.startswith(w):
                text = text[len(w):].strip().lstrip(",.!? ")
                break
        if not text:
            speak("I'm here. What do you need?")
            return

        print(f"  📝 Heard: '{text}'")
        response = ask_drflash(text)
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
                           samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32",
                           blocking=True)

            # Check energy
            rms = np.sqrt(np.mean(audio ** 2)) * 32768
            if rms < WAKE_ENERGY_THRESHOLD:
                continue

            # Use Whisper if available (more accurate), else Vosk
            audio_int16 = (audio * 32767).astype(np.int16)
            if _whisper_model is not None:
                text = whisper_transcribe(audio_int16)
            else:
                text = vosk_transcribe(audio_int16)

            if not text:
                continue

            text_lower = text.lower().strip()
            for phrase in WAKE_PHRASES:
                if phrase in text_lower:
                    print(f"  ⚡ Wake: '{text}'")
                    handle_command()
                    break

        except Exception as e:
            print(f"  ⚠ Wake loop error: {e}")
            time.sleep(1)

        time.sleep(0.1)


def on_hotkey():
    if state.busy:
        return
    print(f"\n  ⌨ Hotkey!")
    threading.Thread(target=handle_command, daemon=True).start()


# ─── Server ──────────────────────────────────────────────────

def server_ok() -> bool:
    try:
        return httpx.get(f"{API_URL}/health", timeout=3).status_code == 200
    except Exception:
        return False

def start_server():
    py = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        return False
    print("  🚀 Starting server...")
    subprocess.Popen([str(py), "run_server.py"], cwd=str(PROJECT_DIR),
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
    def on_toggle(i, it):
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
        pystray.MenuItem("👂 Wake Word", on_toggle, checked=lambda it: state.wake_on),
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
            print("  ⚠ Start server manually first")
    else:
        print("  ✅ Server running")

    try:
        keyboard.add_hotkey(HOTKEY, on_hotkey)
        print(f"  ✅ Hotkey: {HOTKEY.upper()}")
    except Exception:
        pass

    # Load models
    print("  Loading Vosk (wake word)...")
    load_vosk()
    print("  ✅ Vosk ready")

    load_whisper()

    if Path(PIPER_MODEL).exists():
        print(f"  ✅ Piper TTS: {Path(PIPER_MODEL).name}")
    else:
        print("  ⚠ Piper model not found — using Windows SAPI fallback")

    t = threading.Thread(target=wake_loop, daemon=True)
    t.start()

    print(f"\n  Say 'Dr. Flash' or press Ctrl+Alt+D\n")
    build_tray().run()
    state.running = False
    print("\n  Stopped.")


if __name__ == "__main__":
    main()
