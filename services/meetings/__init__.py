"""Dr. Flash — Meeting Recorder Service.

Record meetings, auto-transcribe with Vosk (offline), summarize with
Ollama, and organize folder-wise. Each meeting gets:

  data/meetings/YYYY-MM-DD_title/
    ├── audio.wav          — Raw recording
    ├── transcript.txt     — Full transcript
    ├── summary.md         — AI-generated summary
    └── metadata.json      — Title, date, duration, participants, tags
"""

from __future__ import annotations

import json
import os
import threading
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import numpy as np
import sounddevice as sd
from ulid import ULID


class MeetingRecorder:
    """Records audio from the mic, stores as WAV."""

    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self._recording = False
        self._audio_chunks: list[np.ndarray] = []
        self._stream = None
        self._thread = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        if self._recording:
            return
        self._recording = True
        self._audio_chunks = []

        def callback(indata, frames, time_info, status):
            if self._recording:
                self._audio_chunks.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=self.channels,
            dtype="float32", blocksize=int(self.sample_rate * 0.5),
            callback=callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray | None:
        if not self._recording:
            return None
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if not self._audio_chunks:
            return None
        return np.concatenate(self._audio_chunks)

    def save_wav(self, audio: np.ndarray, path: str) -> None:
        audio_int16 = (audio * 32767).astype(np.int16)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_int16.tobytes())

    @property
    def duration_seconds(self) -> float:
        if not self._audio_chunks:
            return 0
        total_samples = sum(c.shape[0] for c in self._audio_chunks)
        return total_samples / self.sample_rate


class MeetingService:
    """Manages meeting lifecycle: record, transcribe, summarize, store."""

    def __init__(self, meetings_dir: str = "./data/meetings",
                 db_path: str = "./data/drflash.db") -> None:
        self._meetings_dir = Path(meetings_dir)
        self._meetings_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._recorder = MeetingRecorder()
        self._active_meeting: dict | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS meetings (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                duration_seconds REAL NOT NULL DEFAULT 0,
                folder_path TEXT NOT NULL,
                audio_path TEXT,
                transcript_path TEXT,
                summary_path TEXT,
                transcript TEXT,
                summary TEXT,
                participants TEXT NOT NULL DEFAULT '[]',
                tags TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'created',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings(date);
        """)
        await self._db.commit()

    async def start_recording(self, title: str, participants: list[str] | None = None,
                               tags: list[str] | None = None) -> dict:
        """Start recording a meeting."""
        if self._recorder.is_recording:
            return {"error": "Already recording a meeting"}

        meeting_id = str(ULID())
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip().replace(" ", "_")
        folder_name = f"{date_str}_{safe_title}"
        folder_path = self._meetings_dir / folder_name
        folder_path.mkdir(parents=True, exist_ok=True)

        self._active_meeting = {
            "id": meeting_id,
            "title": title,
            "date": date_str,
            "folder_path": str(folder_path),
            "participants": participants or [],
            "tags": tags or [],
            "started_at": now.isoformat(),
        }

        # Save metadata
        meta_path = folder_path / "metadata.json"
        meta_path.write_text(json.dumps(self._active_meeting, indent=2))

        # Start recording
        self._recorder.start()

        # Save to DB
        assert self._db
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """INSERT INTO meetings (id, title, date, folder_path, participants, tags, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'recording', ?, ?)""",
            (meeting_id, title, date_str, str(folder_path),
             json.dumps(participants or []), json.dumps(tags or []), now_iso, now_iso)
        )
        await self._db.commit()

        return {"id": meeting_id, "title": title, "status": "recording", "folder": str(folder_path)}

    async def stop_recording(self) -> dict:
        """Stop recording and save audio."""
        if not self._recorder.is_recording or not self._active_meeting:
            return {"error": "No active recording"}

        audio = self._recorder.stop()
        if audio is None:
            return {"error": "No audio captured"}

        meeting = self._active_meeting
        folder = Path(meeting["folder_path"])
        duration = len(audio) / self._recorder.sample_rate

        # Save WAV
        audio_path = folder / "audio.wav"
        self._recorder.save_wav(audio, str(audio_path))

        # Update DB
        assert self._db
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """UPDATE meetings SET status = 'recorded', duration_seconds = ?,
               audio_path = ?, updated_at = ? WHERE id = ?""",
            (duration, str(audio_path), now_iso, meeting["id"])
        )
        await self._db.commit()

        # Update metadata
        meeting["duration_seconds"] = duration
        meeting["audio_path"] = str(audio_path)
        meeting["status"] = "recorded"
        (folder / "metadata.json").write_text(json.dumps(meeting, indent=2))

        self._active_meeting = None

        return {
            "id": meeting["id"], "title": meeting["title"],
            "duration": round(duration, 1), "status": "recorded",
            "audio_path": str(audio_path),
        }

    async def transcribe_meeting(self, meeting_id: str) -> dict:
        """Transcribe a recorded meeting using Vosk (offline)."""
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)

        meeting = await self.get_meeting(meeting_id)
        if not meeting:
            return {"error": "Meeting not found"}
        if not meeting.get("audio_path"):
            return {"error": "No audio file"}

        model_path = str(Path("data/models/vosk-small"))
        if not Path(model_path).exists():
            return {"error": "Vosk model not found. Download it first."}

        model = Model(model_path)
        rec = KaldiRecognizer(model, 16000)
        rec.SetWords(True)

        # Read WAV
        with wave.open(meeting["audio_path"], "rb") as wf:
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                rec.AcceptWaveform(data)

        result = json.loads(rec.FinalResult())
        transcript = result.get("text", "")

        # Save transcript
        folder = Path(meeting["folder_path"])
        transcript_path = folder / "transcript.txt"
        transcript_path.write_text(transcript, encoding="utf-8")

        # Update DB
        assert self._db
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """UPDATE meetings SET status = 'transcribed', transcript = ?,
               transcript_path = ?, updated_at = ? WHERE id = ?""",
            (transcript, str(transcript_path), now_iso, meeting_id)
        )
        await self._db.commit()

        return {"id": meeting_id, "transcript": transcript, "status": "transcribed"}

    async def summarize_meeting(self, meeting_id: str) -> dict:
        """Summarize a transcribed meeting using Ollama."""
        import httpx

        meeting = await self.get_meeting(meeting_id)
        if not meeting or not meeting.get("transcript"):
            return {"error": "No transcript to summarize"}

        prompt = f"""Summarize this meeting transcript concisely. Include:
1. Key discussion points
2. Decisions made
3. Action items (who, what, when)
4. Important notes

Transcript:
{meeting['transcript'][:8000]}"""

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post("http://localhost:11434/api/chat", json={
                    "model": "qwen2.5:7b-instruct-q4_K_M",
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                })
                data = resp.json()
                summary = data.get("message", {}).get("content", "Summary generation failed.")
        except Exception as e:
            summary = f"Error generating summary: {e}"

        # Save summary
        folder = Path(meeting["folder_path"])
        summary_path = folder / "summary.md"
        summary_path.write_text(f"# Meeting: {meeting['title']}\n\n{summary}", encoding="utf-8")

        # Update DB
        assert self._db
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """UPDATE meetings SET status = 'summarized', summary = ?,
               summary_path = ?, updated_at = ? WHERE id = ?""",
            (summary, str(summary_path), now_iso, meeting_id)
        )
        await self._db.commit()

        return {"id": meeting_id, "summary": summary, "status": "summarized"}

    async def get_meeting(self, meeting_id: str) -> dict | None:
        assert self._db
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def list_meetings(self, limit: int = 50) -> list[dict]:
        assert self._db
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            "SELECT id, title, date, duration_seconds, status, folder_path, tags, created_at FROM meetings ORDER BY date DESC LIMIT ?",
            (limit,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]

    async def delete_meeting(self, meeting_id: str) -> bool:
        meeting = await self.get_meeting(meeting_id)
        if not meeting:
            return False
        import shutil
        folder = Path(meeting["folder_path"])
        if folder.exists():
            shutil.rmtree(folder)
        assert self._db
        await self._db.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        await self._db.commit()
        return True

    @property
    def recording_status(self) -> dict:
        if self._recorder.is_recording and self._active_meeting:
            return {
                "recording": True,
                "meeting_id": self._active_meeting["id"],
                "title": self._active_meeting["title"],
                "duration": round(self._recorder.duration_seconds, 1),
            }
        return {"recording": False}

    async def close(self) -> None:
        if self._recorder.is_recording:
            self._recorder.stop()
        if self._db:
            await self._db.close()
            self._db = None
