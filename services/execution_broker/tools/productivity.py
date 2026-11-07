"""Dr. Flash — Productivity Tools.

Practical tools for daily work: clipboard history, file finder,
quick notes, reminders, and timers. All accessible via chat.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from services.contracts.enums import Risk, SideEffect
from services.contracts.models import (
    CapabilityToken, ToolCall, ToolCapability, ToolRegistration, ToolResult,
)
from services.execution_broker import ToolAdapter


class ProductivityTool(ToolAdapter):
    """Clipboard, file finder, notes, reminders — everyday productivity."""

    def __init__(self, notes_dir: str = "./data/workspace/notes") -> None:
        self._notes_dir = Path(notes_dir)
        self._notes_dir.mkdir(parents=True, exist_ok=True)
        self._clipboard_history: list[dict] = []
        self._timers: dict[str, dict] = {}

    @property
    def tool_id(self) -> str:
        return "productivity"

    @property
    def registration(self) -> ToolRegistration:
        return ToolRegistration(
            tool_id="productivity",
            version="0.1.0",
            description="Clipboard, file search, quick notes, timers, and daily productivity.",
            capabilities=[
                ToolCapability(action="read_clipboard", resource_scope="clipboard",
                               side_effect=SideEffect.READ, risk=Risk.R0_READ,
                               description="Read current clipboard content."),
                ToolCapability(action="write_clipboard", resource_scope="clipboard",
                               side_effect=SideEffect.LOCAL_WRITE, risk=Risk.R1_LOCAL_WRITE,
                               description="Copy text to clipboard."),
                ToolCapability(action="find_files", resource_scope="filesystem",
                               side_effect=SideEffect.READ, risk=Risk.R0_READ,
                               description="Search for files by name pattern in a directory."),
                ToolCapability(action="save_note", resource_scope="notes",
                               side_effect=SideEffect.LOCAL_WRITE, risk=Risk.R1_LOCAL_WRITE,
                               description="Save a quick note with title and content."),
                ToolCapability(action="list_notes", resource_scope="notes",
                               side_effect=SideEffect.READ, risk=Risk.R0_READ,
                               description="List all saved notes."),
                ToolCapability(action="read_note", resource_scope="notes",
                               side_effect=SideEffect.READ, risk=Risk.R0_READ,
                               description="Read a specific note by filename."),
                ToolCapability(action="start_timer", resource_scope="system",
                               side_effect=SideEffect.READ, risk=Risk.R0_READ,
                               description="Start a named timer."),
                ToolCapability(action="check_timer", resource_scope="system",
                               side_effect=SideEffect.READ, risk=Risk.R0_READ,
                               description="Check elapsed time on a timer."),
                ToolCapability(action="calculate", resource_scope="system",
                               side_effect=SideEffect.READ, risk=Risk.R0_READ,
                               description="Evaluate a math expression safely."),
            ],
            requires_approval_above=Risk.R2_EXTERNAL_WRITE,
            execution_timeout_seconds=15,
        )

    async def execute(self, call: ToolCall, token: CapabilityToken) -> ToolResult:
        try:
            action = call.action
            if action == "read_clipboard":
                return await self._read_clipboard(call)
            elif action == "write_clipboard":
                return await self._write_clipboard(call)
            elif action == "find_files":
                return await self._find_files(call)
            elif action == "save_note":
                return await self._save_note(call)
            elif action == "list_notes":
                return await self._list_notes(call)
            elif action == "read_note":
                return await self._read_note(call)
            elif action == "start_timer":
                return await self._start_timer(call)
            elif action == "check_timer":
                return await self._check_timer(call)
            elif action == "calculate":
                return await self._calculate(call)
            return ToolResult(call_id=call.call_id, success=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e))

    async def observe(self, scope: str) -> dict:
        return {"type": "productivity", "notes_count": len(list(self._notes_dir.glob("*.md")))}

    async def health(self) -> dict:
        return {"tool_id": self.tool_id, "status": "healthy"}

    async def _read_clipboard(self, call: ToolCall) -> ToolResult:
        try:
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=5,
            )
            content = result.stdout.strip()
            self._clipboard_history.append({
                "content": content[:500], "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return ToolResult(call_id=call.call_id, success=True,
                              data={"content": content[:2000], "length": len(content)})
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e))

    async def _write_clipboard(self, call: ToolCall) -> ToolResult:
        text = call.args.get("text", "")
        if not text:
            return ToolResult(call_id=call.call_id, success=False, error="Text required")
        try:
            subprocess.run(
                ["powershell", "-Command", f"Set-Clipboard -Value '{text[:5000]}'"],
                timeout=5, capture_output=True,
            )
            return ToolResult(call_id=call.call_id, success=True,
                              data={"copied": True, "length": len(text)})
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e))

    async def _find_files(self, call: ToolCall) -> ToolResult:
        pattern = call.args.get("pattern", "*")
        directory = call.args.get("directory", os.path.expanduser("~"))
        max_results = call.args.get("max_results", 20)

        try:
            # Use PowerShell for fast recursive search
            result = subprocess.run(
                ["powershell", "-Command",
                 f"Get-ChildItem -Path '{directory}' -Filter '{pattern}' -Recurse -ErrorAction SilentlyContinue "
                 f"| Select-Object -First {max_results} FullName, Length, LastWriteTime "
                 f"| ConvertTo-Json"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                files = json.loads(result.stdout)
                if isinstance(files, dict):
                    files = [files]
                return ToolResult(call_id=call.call_id, success=True,
                                  data={"files": files, "count": len(files), "pattern": pattern})
            return ToolResult(call_id=call.call_id, success=True,
                              data={"files": [], "count": 0, "pattern": pattern})
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e))

    async def _save_note(self, call: ToolCall) -> ToolResult:
        title = call.args.get("title", "untitled")
        content = call.args.get("content", "")
        if not content:
            return ToolResult(call_id=call.call_id, success=False, error="Content required")

        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip().replace(" ", "_")
        filename = f"{datetime.now().strftime('%Y%m%d')}_{safe_title}.md"
        filepath = self._notes_dir / filename

        full_content = f"# {title}\n\n*Created: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n{content}"
        filepath.write_text(full_content, encoding="utf-8")

        return ToolResult(call_id=call.call_id, success=True,
                          data={"filename": filename, "path": str(filepath)})

    async def _list_notes(self, call: ToolCall) -> ToolResult:
        notes = []
        for f in sorted(self._notes_dir.glob("*.md"), reverse=True)[:30]:
            notes.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return ToolResult(call_id=call.call_id, success=True,
                          data={"notes": notes, "count": len(notes)})

    async def _read_note(self, call: ToolCall) -> ToolResult:
        filename = call.args.get("filename", "")
        if not filename:
            return ToolResult(call_id=call.call_id, success=False, error="Filename required")
        filepath = self._notes_dir / filename
        if not filepath.exists():
            return ToolResult(call_id=call.call_id, success=False, error="Note not found")
        content = filepath.read_text(encoding="utf-8")
        return ToolResult(call_id=call.call_id, success=True,
                          data={"filename": filename, "content": content[:5000]})

    async def _start_timer(self, call: ToolCall) -> ToolResult:
        name = call.args.get("name", "default")
        self._timers[name] = {"started": time.time(), "name": name}
        return ToolResult(call_id=call.call_id, success=True,
                          data={"timer": name, "started": True})

    async def _check_timer(self, call: ToolCall) -> ToolResult:
        name = call.args.get("name", "default")
        if name not in self._timers:
            return ToolResult(call_id=call.call_id, success=False, error=f"No timer named '{name}'")
        elapsed = time.time() - self._timers[name]["started"]
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        return ToolResult(call_id=call.call_id, success=True,
                          data={"timer": name, "elapsed_seconds": round(elapsed, 1),
                                "display": f"{mins}m {secs}s"})

    async def _calculate(self, call: ToolCall) -> ToolResult:
        expr = call.args.get("expression", "")
        if not expr:
            return ToolResult(call_id=call.call_id, success=False, error="Expression required")
        # Safe math eval
        allowed = set("0123456789+-*/.()% ")
        if not all(c in allowed for c in expr):
            return ToolResult(call_id=call.call_id, success=False,
                              error="Only basic math operations allowed")
        try:
            result = eval(expr, {"__builtins__": {}})
            return ToolResult(call_id=call.call_id, success=True,
                              data={"expression": expr, "result": result})
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e))


class ScreenCaptureTool(ToolAdapter):
    """Screen capture and OCR for answering questions about what's on screen."""

    def __init__(self) -> None:
        from services.screen import ScreenReader
        self._reader = ScreenReader()

    @property
    def tool_id(self) -> str:
        return "screen"

    @property
    def registration(self) -> ToolRegistration:
        return ToolRegistration(
            tool_id="screen",
            version="0.1.0",
            description="Capture screen/window and extract text via OCR.",
            capabilities=[
                ToolCapability(action="capture_screen", resource_scope="screen",
                               side_effect=SideEffect.READ, risk=Risk.R0_READ,
                               description="Take a screenshot of the entire screen."),
                ToolCapability(action="capture_window", resource_scope="screen",
                               side_effect=SideEffect.READ, risk=Risk.R0_READ,
                               description="Take a screenshot of the active window."),
                ToolCapability(action="read_screen", resource_scope="screen",
                               side_effect=SideEffect.READ, risk=Risk.R0_READ,
                               description="Capture screen and extract all text via OCR."),
            ],
            requires_approval_above=Risk.R2_EXTERNAL_WRITE,
            execution_timeout_seconds=20,
        )

    async def execute(self, call: ToolCall, token: CapabilityToken) -> ToolResult:
        try:
            if call.action == "capture_screen":
                result = self._reader.capture_screen()
                return ToolResult(call_id=call.call_id, success=True, data=result)
            elif call.action == "capture_window":
                result = self._reader.capture_active_window()
                return ToolResult(call_id=call.call_id, success=True, data=result)
            elif call.action == "read_screen":
                capture = self._reader.capture_screen()
                text = self._reader.extract_text(capture["path"])
                return ToolResult(call_id=call.call_id, success=True,
                                  data={"text": text[:5000], "capture": capture})
            return ToolResult(call_id=call.call_id, success=False, error=f"Unknown: {call.action}")
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e))

    async def observe(self, scope: str) -> dict:
        return {"type": "screen"}

    async def health(self) -> dict:
        return {"tool_id": self.tool_id, "status": "healthy"}


class MeetingTool(ToolAdapter):
    """Meeting recording tool accessible via chat."""

    def __init__(self, meeting_service) -> None:
        self._meetings = meeting_service

    @property
    def tool_id(self) -> str:
        return "meetings"

    @property
    def registration(self) -> ToolRegistration:
        return ToolRegistration(
            tool_id="meetings",
            version="0.1.0",
            description="Record, transcribe, and summarize meetings.",
            capabilities=[
                ToolCapability(action="start_recording", resource_scope="meetings",
                               side_effect=SideEffect.LOCAL_WRITE, risk=Risk.R1_LOCAL_WRITE,
                               description="Start recording a meeting. Args: title, participants (optional)."),
                ToolCapability(action="stop_recording", resource_scope="meetings",
                               side_effect=SideEffect.LOCAL_WRITE, risk=Risk.R1_LOCAL_WRITE,
                               description="Stop recording the current meeting."),
                ToolCapability(action="list_meetings", resource_scope="meetings",
                               side_effect=SideEffect.READ, risk=Risk.R0_READ,
                               description="List all recorded meetings."),
                ToolCapability(action="transcribe", resource_scope="meetings",
                               side_effect=SideEffect.LOCAL_WRITE, risk=Risk.R1_LOCAL_WRITE,
                               description="Transcribe a recorded meeting. Args: meeting_id."),
                ToolCapability(action="summarize", resource_scope="meetings",
                               side_effect=SideEffect.LOCAL_WRITE, risk=Risk.R1_LOCAL_WRITE,
                               description="Generate AI summary of a meeting. Args: meeting_id."),
                ToolCapability(action="recording_status", resource_scope="meetings",
                               side_effect=SideEffect.READ, risk=Risk.R0_READ,
                               description="Check if a meeting is currently being recorded."),
            ],
            requires_approval_above=Risk.R2_EXTERNAL_WRITE,
            execution_timeout_seconds=120,
        )

    async def execute(self, call: ToolCall, token: CapabilityToken) -> ToolResult:
        try:
            if call.action == "start_recording":
                title = call.args.get("title", f"Meeting {datetime.now().strftime('%H:%M')}")
                participants = call.args.get("participants", [])
                result = await self._meetings.start_recording(title, participants)
                return ToolResult(call_id=call.call_id, success="error" not in result, data=result)
            elif call.action == "stop_recording":
                result = await self._meetings.stop_recording()
                return ToolResult(call_id=call.call_id, success="error" not in result, data=result)
            elif call.action == "list_meetings":
                meetings = await self._meetings.list_meetings()
                return ToolResult(call_id=call.call_id, success=True, data={"meetings": meetings})
            elif call.action == "transcribe":
                mid = call.args.get("meeting_id", "")
                result = await self._meetings.transcribe_meeting(mid)
                return ToolResult(call_id=call.call_id, success="error" not in result, data=result)
            elif call.action == "summarize":
                mid = call.args.get("meeting_id", "")
                result = await self._meetings.summarize_meeting(mid)
                return ToolResult(call_id=call.call_id, success="error" not in result, data=result)
            elif call.action == "recording_status":
                return ToolResult(call_id=call.call_id, success=True,
                                  data=self._meetings.recording_status)
            return ToolResult(call_id=call.call_id, success=False, error=f"Unknown: {call.action}")
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e))

    async def observe(self, scope: str) -> dict:
        return {"type": "meetings", **self._meetings.recording_status}

    async def health(self) -> dict:
        return {"tool_id": self.tool_id, "status": "healthy"}
