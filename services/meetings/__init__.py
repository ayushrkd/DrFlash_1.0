"""Dr. Flash — Meeting Recorder Service.

Handles real meetings up to 2+ hours:
- Records audio in chunks (5 min WAV files) to avoid memory issues
- Transcribes each chunk independently with Vosk
- Summarizes with Ollama in stages
- Stores everything organized by folder

Structure:
  data/meetings/YYYY-MM-DD_title/
    ├── chunks/
    │   ├── chunk_001.wav
    │   ├── chunk_002.wav
    │   └── ...
    ├── transcript.txt       — Full combined transcript
    ├── transcript_chunks/
    │   ├── chunk_001.txt
    │   └── ...
    ├── summary.md           — AI summary
    └── metadata.json
"""

from __future__ import annotations

import json
import threading
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import numpy as np
import sounddevice as sd
from ulid import ULID


CHUNK_DURATION_SECONDS = 300  # 5 minutes per chunk
SAMPLE_RATE = 16000
CHANNELS = 1


class MeetingRecorder:
    """Records audio in 5-minute chunks. Can handle hours of recording."""

    def __init__(self, output_dir: str, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self._output_dir = Path(output_dir)
        self._chunks_dir = self._output_dir / "chunks"
        self._recording = False
        self._current_chunk: list[np.ndarray] = []
        self._chunk_index = 0
        self._stream = None
        self._start_time = 0.0
        self._chunk_start_time = 0.0
        self._total_samples = 0
        self._lock = threading.Lock()

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def duration(self) -> float:
        if not self._recording:
            return self._total_samples / self.sample_rate
        return time.time() - self._start_time

    @property
    def chunk_count(self) -> int:
        return self._chunk_index

    def start(self) -> None:
        if self._recording:
            return
        self._chunks_dir.mkdir(parents=True, exist_ok=True)
        self._recording = True
        self._chunk_index = 0
        self._current_chunk = []
        self._start_time = time.time()
        self._chunk_start_time = time.time()
        self._total_samples = 0

        def callback(indata, frames, time_info, status):
            if not self._recording:
                return
            with self._lock:
                self._current_chunk.append(indata.copy())
                self._total_samples += frames

                # Check if chunk is full (5 minutes)
                elapsed = time.time() - self._chunk_start_time
                if elapsed >= CHUNK_DURATION_SECONDS:
                    self._save_chunk()

        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=CHANNELS,
            dtype="float32", blocksize=int(self.sample_rate * 0.5),
            callback=callback,
        )
        self._stream.start()

    def _save_chunk(self) -> str | None:
        """Save current chunk to WAV file."""
        if not self._current_chunk:
            return None

        self._chunk_index += 1
        filename = f"chunk_{self._chunk_index:03d}.wav"
        filepath = self._chunks_dir / filename

        audio = np.concatenate(self._current_chunk)
        audio_int16 = (audio * 32767).astype(np.int16)

        with wave.open(str(filepath), "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_int16.tobytes())

        self._current_chunk = []
        self._chunk_start_time = time.time()
        print(f"    📦 Saved chunk {self._chunk_index} ({filepath.name})")
        return str(filepath)

    def stop(self) -> dict:
        """Stop recording, save final chunk."""
        if not self._recording:
            return {"error": "Not recording"}
        self._recording = False

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        # Save remaining audio
        with self._lock:
            if self._current_chunk:
                self._save_chunk()

        total_duration = self._total_samples / self.sample_rate
        chunk_files = sorted(self._chunks_dir.glob("chunk_*.wav"))

        return {
            "duration_seconds": round(total_duration, 1),
            "chunks": len(chunk_files),
            "chunk_files": [str(f) for f in chunk_files],
        }


class MeetingService:
    """Manages meeting lifecycle with chunked recording and transcription."""

    def __init__(self, meetings_dir: str = "./data/meetings",
                 db_path: str = "./data/drflash.db") -> None:
        self._meetings_dir = Path(meetings_dir)
        self._meetings_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._recorder: MeetingRecorder | None = None
        self._active_meeting: dict | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS meetings (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                duration_seconds REAL NOT NULL DEFAULT 0,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                folder_path TEXT NOT NULL,
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
        if self._recorder and self._recorder.is_recording:
            return {"error": "Already recording. Stop the current meeting first."}

        meeting_id = str(ULID())
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip().replace(" ", "_")
        folder_name = f"{date_str}_{safe_title}"
        folder_path = self._meetings_dir / folder_name
        folder_path.mkdir(parents=True, exist_ok=True)

        self._active_meeting = {
            "id": meeting_id, "title": title, "date": date_str,
            "folder_path": str(folder_path),
            "participants": participants or [], "tags": tags or [],
        }

        # Save initial metadata
        (folder_path / "metadata.json").write_text(json.dumps(self._active_meeting, indent=2))

        # Start chunked recording
        self._recorder = MeetingRecorder(output_dir=str(folder_path))
        self._recorder.start()

        assert self._db
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """INSERT INTO meetings (id, title, date, folder_path, participants, tags, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'recording', ?, ?)""",
            (meeting_id, title, date_str, str(folder_path),
             json.dumps(participants or []), json.dumps(tags or []), now_iso, now_iso)
        )
        await self._db.commit()

        return {"id": meeting_id, "title": title, "status": "recording",
                "folder": str(folder_path), "message": f"Recording started. Audio saves in 5-minute chunks."}

    async def stop_recording(self) -> dict:
        if not self._recorder or not self._recorder.is_recording or not self._active_meeting:
            return {"error": "No active recording"}

        result = self._recorder.stop()
        meeting = self._active_meeting

        assert self._db
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """UPDATE meetings SET status = 'recorded', duration_seconds = ?,
               chunk_count = ?, updated_at = ? WHERE id = ?""",
            (result["duration_seconds"], result["chunks"], now_iso, meeting["id"])
        )
        await self._db.commit()

        # Update metadata
        meeting.update(result)
        meeting["status"] = "recorded"
        folder = Path(meeting["folder_path"])
        (folder / "metadata.json").write_text(json.dumps(meeting, indent=2, default=str))

        mid = meeting["id"]
        self._active_meeting = None
        self._recorder = None

        mins = int(result["duration_seconds"] // 60)
        secs = int(result["duration_seconds"] % 60)

        return {
            "id": mid, "title": meeting["title"],
            "duration": f"{mins}m {secs}s",
            "chunks": result["chunks"],
            "status": "recorded",
            "message": f"Recording stopped. {result['chunks']} chunk(s), {mins}m {secs}s total. Ready to transcribe.",
        }

    async def transcribe_meeting(self, meeting_id: str) -> dict:
        """Transcribe a meeting chunk by chunk using Vosk."""
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)

        meeting = await self.get_meeting(meeting_id)
        if not meeting:
            return {"error": "Meeting not found"}

        folder = Path(meeting["folder_path"])
        chunks_dir = folder / "chunks"
        if not chunks_dir.exists():
            return {"error": "No audio chunks found"}

        model_path = str(Path("data/models/vosk-small"))
        if not Path(model_path).exists():
            return {"error": "Vosk model not found"}

        model = Model(model_path)
        transcript_dir = folder / "transcript_chunks"
        transcript_dir.mkdir(exist_ok=True)

        full_transcript = []
        chunk_files = sorted(chunks_dir.glob("chunk_*.wav"))

        for i, chunk_file in enumerate(chunk_files, 1):
            print(f"    Transcribing chunk {i}/{len(chunk_files)}: {chunk_file.name}")
            rec = KaldiRecognizer(model, SAMPLE_RATE)

            with wave.open(str(chunk_file), "rb") as wf:
                while True:
                    data = wf.readframes(4000)
                    if len(data) == 0:
                        break
                    rec.AcceptWaveform(data)

            result = json.loads(rec.FinalResult())
            chunk_text = result.get("text", "")

            # Save chunk transcript
            (transcript_dir / f"chunk_{i:03d}.txt").write_text(chunk_text, encoding="utf-8")
            if chunk_text.strip():
                full_transcript.append(f"[Chunk {i}, ~{(i-1)*5}-{i*5} min]\n{chunk_text}")

        combined = "\n\n".join(full_transcript)

        # Save full transcript
        (folder / "transcript.txt").write_text(combined, encoding="utf-8")

        assert self._db
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE meetings SET status = 'transcribed', transcript = ?, updated_at = ? WHERE id = ?",
            (combined, now_iso, meeting_id)
        )
        await self._db.commit()

        return {
            "id": meeting_id, "status": "transcribed",
            "chunks_transcribed": len(chunk_files),
            "transcript_preview": combined[:500],
            "transcript_length": len(combined),
        }

    async def summarize_meeting(self, meeting_id: str) -> dict:
        """Summarize meeting using Ollama. For long meetings, summarize in stages."""
        import httpx

        meeting = await self.get_meeting(meeting_id)
        if not meeting or not meeting.get("transcript"):
            return {"error": "No transcript to summarize. Transcribe first."}

        transcript = meeting["transcript"]

        # For long transcripts, summarize in chunks then combine
        if len(transcript) > 6000:
            # Stage 1: Summarize each section
            sections = []
            chunk_size = 4000
            for i in range(0, len(transcript), chunk_size):
                section = transcript[i:i + chunk_size]
                sections.append(section)

            section_summaries = []
            for i, section in enumerate(sections):
                prompt = f"Briefly summarize this part ({i+1}/{len(sections)}) of a meeting transcript:\n\n{section}"
                try:
                    async with httpx.AsyncClient(timeout=120.0) as client:
                        resp = await client.post("http://localhost:11434/api/chat", json={
                            "model": "qwen2.5:7b-instruct-q4_K_M",
                            "messages": [{"role": "user", "content": prompt}],
                            "stream": False,
                        })
                        data = resp.json()
                        section_summaries.append(data.get("message", {}).get("content", ""))
                except Exception as e:
                    section_summaries.append(f"[Error summarizing section {i+1}: {e}]")

            # Stage 2: Combine summaries into final
            combined_summaries = "\n\n".join(f"Part {i+1}: {s}" for i, s in enumerate(section_summaries))
            final_prompt = f"""Create a comprehensive meeting summary from these section summaries.
Include: Key Discussion Points, Decisions Made, Action Items, Important Notes.

Meeting: {meeting['title']}
Date: {meeting['date']}

{combined_summaries}"""
        else:
            final_prompt = f"""Summarize this meeting transcript. Include:
1. Key Discussion Points
2. Decisions Made
3. Action Items (who, what, when)
4. Important Notes

Meeting: {meeting['title']}
Date: {meeting['date']}

{transcript}"""

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post("http://localhost:11434/api/chat", json={
                    "model": "qwen2.5:7b-instruct-q4_K_M",
                    "messages": [{"role": "user", "content": final_prompt}],
                    "stream": False,
                })
                summary = resp.json().get("message", {}).get("content", "Summary failed.")
        except Exception as e:
            summary = f"Error: {e}"

        folder = Path(meeting["folder_path"])
        summary_md = f"# Meeting: {meeting['title']}\n**Date:** {meeting['date']}\n\n{summary}"
        (folder / "summary.md").write_text(summary_md, encoding="utf-8")

        assert self._db
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE meetings SET status = 'summarized', summary = ?, updated_at = ? WHERE id = ?",
            (summary, now_iso, meeting_id)
        )
        await self._db.commit()

        return {"id": meeting_id, "status": "summarized", "summary": summary}

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
            """SELECT id, title, date, duration_seconds, chunk_count, status,
               folder_path, tags, created_at FROM meetings ORDER BY date DESC LIMIT ?""",
            (limit,)
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]

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
        if self._recorder and self._recorder.is_recording and self._active_meeting:
            return {
                "recording": True,
                "meeting_id": self._active_meeting["id"],
                "title": self._active_meeting["title"],
                "duration": round(self._recorder.duration, 1),
                "chunks_saved": self._recorder.chunk_count,
            }
        return {"recording": False}

    async def close(self) -> None:
        if self._recorder and self._recorder.is_recording:
            self._recorder.stop()
        if self._db:
            await self._db.close()
            self._db = None
