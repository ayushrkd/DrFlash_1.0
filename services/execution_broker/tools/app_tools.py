"""JARVIS — App Launcher & Web Tools.

Open URLs, launch applications, and perform web searches.
All actions go through policy with appropriate risk levels.
"""

from __future__ import annotations

import json
import subprocess
import webbrowser
from datetime import datetime, timezone

from services.contracts.enums import Risk, SideEffect
from services.contracts.models import (
    CapabilityToken,
    ToolCall,
    ToolCapability,
    ToolRegistration,
    ToolResult,
)
from services.execution_broker import ToolAdapter


class AppLauncherTool(ToolAdapter):
    """Launch approved applications and open URLs."""

    ALLOWED_APPS = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "explorer": "explorer.exe",
        "terminal": "wt.exe",
        "settings": "ms-settings:",
        "task_manager": "taskmgr.exe",
    }

    @property
    def tool_id(self) -> str:
        return "system.launcher"

    @property
    def registration(self) -> ToolRegistration:
        return ToolRegistration(
            tool_id="system.launcher",
            version="0.1.0",
            description="Open approved applications, URLs, and file locations.",
            capabilities=[
                ToolCapability(
                    action="open_url",
                    resource_scope="web",
                    side_effect=SideEffect.LOCAL_WRITE,
                    risk=Risk.R1_LOCAL_WRITE,
                    description="Open a URL in the default browser.",
                ),
                ToolCapability(
                    action="open_app",
                    resource_scope="system",
                    side_effect=SideEffect.LOCAL_WRITE,
                    risk=Risk.R1_LOCAL_WRITE,
                    description="Launch an approved application (notepad, calculator, explorer, terminal, settings).",
                ),
                ToolCapability(
                    action="open_folder",
                    resource_scope="filesystem",
                    side_effect=SideEffect.LOCAL_WRITE,
                    risk=Risk.R1_LOCAL_WRITE,
                    description="Open a folder in File Explorer.",
                ),
                ToolCapability(
                    action="web_search",
                    resource_scope="web",
                    side_effect=SideEffect.LOCAL_WRITE,
                    risk=Risk.R1_LOCAL_WRITE,
                    description="Search the web using DuckDuckGo (opens in browser).",
                ),
            ],
            requires_approval_above=Risk.R2_EXTERNAL_WRITE,
            execution_timeout_seconds=10,
        )

    async def execute(self, call: ToolCall, token: CapabilityToken) -> ToolResult:
        try:
            if call.action == "open_url":
                return await self._open_url(call)
            elif call.action == "open_app":
                return await self._open_app(call)
            elif call.action == "open_folder":
                return await self._open_folder(call)
            elif call.action == "web_search":
                return await self._web_search(call)
            return ToolResult(call_id=call.call_id, success=False, error=f"Unknown action: {call.action}")
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e))

    async def observe(self, scope: str) -> dict:
        return {"type": "launcher", "timestamp": datetime.now(timezone.utc).isoformat()}

    async def health(self) -> dict:
        return {"tool_id": self.tool_id, "status": "healthy"}

    async def _open_url(self, call: ToolCall) -> ToolResult:
        url = call.args.get("url", "")
        if not url:
            return ToolResult(call_id=call.call_id, success=False, error="URL is required")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)
        return ToolResult(call_id=call.call_id, success=True, data={"opened": url})

    async def _open_app(self, call: ToolCall) -> ToolResult:
        app_name = call.args.get("app", "").lower()
        if app_name not in self.ALLOWED_APPS:
            return ToolResult(
                call_id=call.call_id, success=False,
                error=f"App '{app_name}' not in allowed list. Available: {list(self.ALLOWED_APPS.keys())}",
            )
        cmd = self.ALLOWED_APPS[app_name]
        subprocess.Popen(cmd, shell=True)
        return ToolResult(call_id=call.call_id, success=True, data={"launched": app_name, "command": cmd})

    async def _open_folder(self, call: ToolCall) -> ToolResult:
        folder = call.args.get("path", "")
        if not folder:
            return ToolResult(call_id=call.call_id, success=False, error="Path is required")
        from pathlib import Path as P
        target = P(folder).resolve()
        if not target.is_dir():
            return ToolResult(call_id=call.call_id, success=False, error=f"Not a directory: {folder}")
        subprocess.Popen(f'explorer "{target}"')
        return ToolResult(call_id=call.call_id, success=True, data={"opened": str(target)})

    async def _web_search(self, call: ToolCall) -> ToolResult:
        query = call.args.get("query", "")
        if not query:
            return ToolResult(call_id=call.call_id, success=False, error="Query is required")
        import urllib.parse
        url = f"https://duckduckgo.com/?q={urllib.parse.quote_plus(query)}"
        webbrowser.open(url)
        return ToolResult(call_id=call.call_id, success=True, data={"searched": query, "url": url})


class CodeRunnerTool(ToolAdapter):
    """Sandboxed Python code execution with resource limits."""

    def __init__(self, sandbox_root: str = "./sandbox") -> None:
        self._sandbox = subprocess.os.path.abspath(sandbox_root)

    @property
    def tool_id(self) -> str:
        return "sandbox.code"

    @property
    def registration(self) -> ToolRegistration:
        return ToolRegistration(
            tool_id="sandbox.code",
            version="0.1.0",
            description="Execute Python code in a sandboxed environment with output capture.",
            capabilities=[
                ToolCapability(
                    action="run_python",
                    resource_scope="sandbox",
                    side_effect=SideEffect.LOCAL_WRITE,
                    risk=Risk.R1_LOCAL_WRITE,
                    description="Run Python code and return stdout/stderr. Limited to 10 second timeout.",
                ),
                ToolCapability(
                    action="run_shell",
                    resource_scope="sandbox",
                    side_effect=SideEffect.LOCAL_WRITE,
                    risk=Risk.R1_LOCAL_WRITE,
                    description="Run a safe shell command (dir, echo, type, where, python --version, etc.).",
                ),
            ],
            requires_approval_above=Risk.R2_EXTERNAL_WRITE,
            execution_timeout_seconds=15,
        )

    SAFE_COMMANDS = {"dir", "echo", "type", "where", "python", "pip", "git", "node", "pnpm", "dotnet", "hostname", "whoami", "date", "time", "systeminfo"}

    async def execute(self, call: ToolCall, token: CapabilityToken) -> ToolResult:
        try:
            if call.action == "run_python":
                return await self._run_python(call)
            elif call.action == "run_shell":
                return await self._run_shell(call)
            return ToolResult(call_id=call.call_id, success=False, error=f"Unknown action: {call.action}")
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e))

    async def observe(self, scope: str) -> dict:
        return {"type": "code_runner", "sandbox": self._sandbox}

    async def health(self) -> dict:
        return {"tool_id": self.tool_id, "status": "healthy"}

    async def _run_python(self, call: ToolCall) -> ToolResult:
        code = call.args.get("code", "")
        if not code:
            return ToolResult(call_id=call.call_id, success=False, error="Code is required")

        # Block dangerous operations
        dangerous = ["import os", "os.system", "subprocess", "shutil.rmtree", "__import__",
                      "eval(", "exec(", "open(", "pathlib", "socket", "http"]
        for d in dangerous:
            if d in code:
                return ToolResult(call_id=call.call_id, success=False,
                                  error=f"Blocked: code contains disallowed operation '{d}'")

        try:
            result = subprocess.run(
                ["python", "-c", code],
                capture_output=True, text=True, timeout=10,
                cwd=self._sandbox,
            )
            return ToolResult(
                call_id=call.call_id,
                success=result.returncode == 0,
                data={
                    "stdout": result.stdout[:5000],
                    "stderr": result.stderr[:2000],
                    "return_code": result.returncode,
                },
                error=result.stderr[:500] if result.returncode != 0 else None,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(call_id=call.call_id, success=False, error="Code execution timed out (10s limit)")

    async def _run_shell(self, call: ToolCall) -> ToolResult:
        command = call.args.get("command", "")
        if not command:
            return ToolResult(call_id=call.call_id, success=False, error="Command is required")

        # Whitelist check
        base_cmd = command.strip().split()[0].lower()
        if base_cmd not in self.SAFE_COMMANDS:
            return ToolResult(
                call_id=call.call_id, success=False,
                error=f"Command '{base_cmd}' not in safe list. Allowed: {sorted(self.SAFE_COMMANDS)}",
            )

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=10,
                cwd=self._sandbox,
            )
            return ToolResult(
                call_id=call.call_id,
                success=result.returncode == 0,
                data={
                    "stdout": result.stdout[:5000],
                    "stderr": result.stderr[:2000],
                    "return_code": result.returncode,
                },
            )
        except subprocess.TimeoutExpired:
            return ToolResult(call_id=call.call_id, success=False, error="Command timed out (10s limit)")
