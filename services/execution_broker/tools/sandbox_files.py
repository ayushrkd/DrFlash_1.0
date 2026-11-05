"""JARVIS — Sandbox File Tools.

Restricted file operations within the sandbox directory only.
These are the first real tools, demonstrating the full pipeline:
registration -> policy -> execution -> verification.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from services.contracts.enums import Risk, SideEffect
from services.contracts.models import (
    CapabilityToken,
    ToolCall,
    ToolCapability,
    ToolRegistration,
    ToolResult,
)
from services.execution_broker import ToolAdapter


class SandboxFilesTool(ToolAdapter):
    """File operations restricted to a sandbox directory."""

    def __init__(self, sandbox_root: str = "./sandbox") -> None:
        self._sandbox = Path(sandbox_root).resolve()
        self._sandbox.mkdir(parents=True, exist_ok=True)
        (self._sandbox / "workspace").mkdir(exist_ok=True)
        (self._sandbox / "fixtures").mkdir(exist_ok=True)

    @property
    def tool_id(self) -> str:
        return "sandbox.files"

    @property
    def registration(self) -> ToolRegistration:
        return ToolRegistration(
            tool_id="sandbox.files",
            version="0.1.0",
            description="File operations restricted to the sandbox directory.",
            capabilities=[
                ToolCapability(
                    action="list_files",
                    resource_scope=str(self._sandbox),
                    side_effect=SideEffect.READ,
                    risk=Risk.R0_READ,
                    description="List files in a sandbox directory.",
                ),
                ToolCapability(
                    action="read_file",
                    resource_scope=str(self._sandbox),
                    side_effect=SideEffect.READ,
                    risk=Risk.R0_READ,
                    description="Read a file from the sandbox.",
                ),
                ToolCapability(
                    action="write_report",
                    resource_scope=str(self._sandbox / "workspace"),
                    side_effect=SideEffect.LOCAL_WRITE,
                    risk=Risk.R1_LOCAL_WRITE,
                    description="Write a report file to sandbox/workspace.",
                ),
            ],
            requires_approval_above=Risk.R2_EXTERNAL_WRITE,
            execution_timeout_seconds=30,
        )

    async def execute(self, call: ToolCall, token: CapabilityToken) -> ToolResult:
        try:
            if call.action == "list_files":
                return await self._list_files(call)
            elif call.action == "read_file":
                return await self._read_file(call)
            elif call.action == "write_report":
                return await self._write_report(call)
            else:
                return ToolResult(
                    call_id=call.call_id,
                    success=False,
                    error=f"Unknown action: {call.action}",
                )
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e))

    async def observe(self, scope: str) -> dict:
        """Observe current state of the sandbox for verification."""
        target = Path(scope) if scope else self._sandbox
        if not target.is_absolute():
            target = self._sandbox / target

        if not self._is_safe_path(target):
            return {"error": "path outside sandbox"}

        if target.is_file():
            content = target.read_text(encoding="utf-8", errors="replace")
            return {
                "type": "file",
                "path": str(target),
                "size": target.stat().st_size,
                "hash": hashlib.sha256(content.encode()).hexdigest(),
                "modified": target.stat().st_mtime,
            }
        elif target.is_dir():
            files = sorted(target.rglob("*"))
            return {
                "type": "directory",
                "path": str(target),
                "file_count": len([f for f in files if f.is_file()]),
                "files": [str(f.relative_to(self._sandbox)) for f in files if f.is_file()][:50],
            }
        return {"type": "not_found", "path": str(target)}

    async def health(self) -> dict:
        return {
            "tool_id": self.tool_id,
            "status": "healthy",
            "sandbox_exists": self._sandbox.exists(),
            "sandbox_path": str(self._sandbox),
        }

    # ── Private implementations ──────────────────────────────────────

    async def _list_files(self, call: ToolCall) -> ToolResult:
        directory = call.args.get("directory", "")
        target = (self._sandbox / directory).resolve()

        if not self._is_safe_path(target):
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error="Path outside sandbox boundary",
            )

        if not target.is_dir():
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=f"Directory not found: {directory}",
            )

        files = []
        for item in sorted(target.iterdir()):
            files.append({
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else 0,
            })

        return ToolResult(
            call_id=call.call_id,
            success=True,
            data={"directory": str(target.relative_to(self._sandbox)), "files": files},
        )

    async def _read_file(self, call: ToolCall) -> ToolResult:
        file_path = call.args.get("path", "")
        target = (self._sandbox / file_path).resolve()

        if not self._is_safe_path(target):
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error="Path outside sandbox boundary",
            )

        if not target.is_file():
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=f"File not found: {file_path}",
            )

        content = target.read_text(encoding="utf-8", errors="replace")
        return ToolResult(
            call_id=call.call_id,
            success=True,
            data={
                "path": str(target.relative_to(self._sandbox)),
                "content": content[:10000],  # bounded read
                "size_bytes": len(content),
                "hash": hashlib.sha256(content.encode()).hexdigest(),
            },
        )

    async def _write_report(self, call: ToolCall) -> ToolResult:
        output_path = call.args.get("output_path", "")
        content = call.args.get("content", "")

        if not output_path:
            return ToolResult(
                call_id=call.call_id, success=False, error="output_path is required"
            )

        target = (self._sandbox / "workspace" / output_path).resolve()

        if not self._is_safe_path(target):
            return ToolResult(
                call_id=call.call_id, success=False, error="Path outside sandbox/workspace"
            )

        # Atomic write: write to temp then rename
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target.with_suffix(target.suffix + ".tmp")
        try:
            temp_path.write_text(content, encoding="utf-8")
            temp_path.replace(target)
        except Exception as e:
            temp_path.unlink(missing_ok=True)
            return ToolResult(call_id=call.call_id, success=False, error=str(e))

        content_hash = hashlib.sha256(content.encode()).hexdigest()
        return ToolResult(
            call_id=call.call_id,
            success=True,
            data={
                "path": str(target.relative_to(self._sandbox)),
                "size_bytes": len(content),
                "hash": content_hash,
            },
        )

    def _is_safe_path(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self._sandbox)
            return True
        except ValueError:
            return False
