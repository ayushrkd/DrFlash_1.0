"""JARVIS — System Tools.

Real system information and control tools. These provide JARVIS with
actual awareness of the machine it's running on.
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
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


class SystemInfoTool(ToolAdapter):
    """Read-only system information: CPU, memory, disk, processes, network."""

    @property
    def tool_id(self) -> str:
        return "system.info"

    @property
    def registration(self) -> ToolRegistration:
        return ToolRegistration(
            tool_id="system.info",
            version="0.1.0",
            description="Read-only system information: hardware, OS, processes, disk usage.",
            capabilities=[
                ToolCapability(
                    action="get_system_info",
                    resource_scope="system",
                    side_effect=SideEffect.READ,
                    risk=Risk.R0_READ,
                    description="Get OS, CPU, RAM, GPU, and disk information.",
                ),
                ToolCapability(
                    action="list_processes",
                    resource_scope="system",
                    side_effect=SideEffect.READ,
                    risk=Risk.R0_READ,
                    description="List running processes with CPU/memory usage.",
                ),
                ToolCapability(
                    action="get_datetime",
                    resource_scope="system",
                    side_effect=SideEffect.READ,
                    risk=Risk.R0_READ,
                    description="Get current date, time, and timezone.",
                ),
                ToolCapability(
                    action="get_disk_usage",
                    resource_scope="system",
                    side_effect=SideEffect.READ,
                    risk=Risk.R0_READ,
                    description="Get disk space usage for all drives.",
                ),
            ],
            requires_approval_above=Risk.R2_EXTERNAL_WRITE,
            execution_timeout_seconds=10,
        )

    async def execute(self, call: ToolCall, token: CapabilityToken) -> ToolResult:
        try:
            if call.action == "get_system_info":
                return await self._system_info(call)
            elif call.action == "list_processes":
                return await self._list_processes(call)
            elif call.action == "get_datetime":
                return await self._get_datetime(call)
            elif call.action == "get_disk_usage":
                return await self._disk_usage(call)
            return ToolResult(call_id=call.call_id, success=False, error=f"Unknown action: {call.action}")
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e))

    async def observe(self, scope: str) -> dict:
        return {"type": "system", "timestamp": datetime.now(timezone.utc).isoformat()}

    async def health(self) -> dict:
        return {"tool_id": self.tool_id, "status": "healthy"}

    async def _system_info(self, call: ToolCall) -> ToolResult:
        import shutil
        info = {
            "os": platform.system(),
            "os_version": platform.version(),
            "os_release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "hostname": platform.node(),
            "cpu_count": os.cpu_count(),
        }

        # Memory via OS
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "[math]::Round((Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize/1MB,1)"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                info["ram_gb"] = float(result.stdout.strip())
        except Exception:
            pass

        # GPU
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                info["gpu"] = result.stdout.strip()
        except Exception:
            pass

        # Disk
        total, used, free = shutil.disk_usage("/")
        info["disk"] = {
            "total_gb": round(total / (1024**3), 1),
            "used_gb": round(used / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1),
        }

        return ToolResult(call_id=call.call_id, success=True, data=info)

    async def _list_processes(self, call: ToolCall) -> ToolResult:
        top_n = call.args.get("top_n", 15)
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"Get-Process | Sort-Object -Property WorkingSet64 -Descending | "
                 f"Select-Object -First {top_n} Name, Id, "
                 f"@{{Name='CPU_s';Expression={{[math]::Round($_.CPU,1)}}}}, "
                 f"@{{Name='Mem_MB';Expression={{[math]::Round($_.WorkingSet64/1MB,1)}}}} | "
                 f"ConvertTo-Json"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                import json
                processes = json.loads(result.stdout)
                if isinstance(processes, dict):
                    processes = [processes]
                return ToolResult(call_id=call.call_id, success=True,
                                  data={"processes": processes, "count": len(processes)})
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e))

        return ToolResult(call_id=call.call_id, success=False, error="Failed to list processes")

    async def _get_datetime(self, call: ToolCall) -> ToolResult:
        now = datetime.now()
        utc_now = datetime.now(timezone.utc)
        return ToolResult(call_id=call.call_id, success=True, data={
            "local_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "utc_time": utc_now.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": time.tzname[0],
            "day_of_week": now.strftime("%A"),
            "date_human": now.strftime("%B %d, %Y"),
        })

    async def _disk_usage(self, call: ToolCall) -> ToolResult:
        import shutil
        drives = []
        for letter in "CDEFGH":
            path = f"{letter}:\\"
            try:
                total, used, free = shutil.disk_usage(path)
                drives.append({
                    "drive": path,
                    "total_gb": round(total / (1024**3), 1),
                    "used_gb": round(used / (1024**3), 1),
                    "free_gb": round(free / (1024**3), 1),
                    "used_percent": round(used / total * 100, 1),
                })
            except Exception:
                continue
        return ToolResult(call_id=call.call_id, success=True, data={"drives": drives})
