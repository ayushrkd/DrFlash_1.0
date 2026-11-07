"""Dr. Flash — Screen Reader Service.

Captures the screen, extracts text (OCR), and enables Dr. Flash
to answer questions about what's visible on screen.

Uses:
- mss for fast screen capture
- Windows OCR via PowerShell (built-in, no extra install)
- Ollama for understanding and answering questions
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import mss
import mss.tools
from PIL import Image


class ScreenReader:
    """Captures screen and extracts text for Dr. Flash to understand."""

    def __init__(self, screenshots_dir: str = "./data/screenshots") -> None:
        self._screenshots_dir = Path(screenshots_dir)
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._last_capture: dict | None = None
        self._last_text: str = ""

    def capture_screen(self, monitor: int = 0) -> dict:
        """Capture the full screen or a specific monitor."""
        with mss.MSS() as sct:
            monitors = sct.monitors
            if monitor >= len(monitors):
                monitor = 0
            screenshot = sct.grab(monitors[monitor])
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

        # Save screenshot
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screen_{timestamp}.png"
        filepath = self._screenshots_dir / filename

        # Resize for efficiency (max 1920px wide)
        if img.width > 1920:
            ratio = 1920 / img.width
            img = img.resize((1920, int(img.height * ratio)), Image.LANCZOS)

        img.save(str(filepath), "PNG", optimize=True)

        self._last_capture = {
            "path": str(filepath),
            "width": img.width,
            "height": img.height,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "monitor": monitor,
        }

        return self._last_capture

    def capture_active_window(self) -> dict:
        """Capture only the active/foreground window."""
        try:
            # Use PowerShell to get foreground window bounds
            result = subprocess.run(
                ["powershell", "-Command", """
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int count);
}
public struct RECT { public int Left, Top, Right, Bottom; }
"@
$hwnd = [Win32]::GetForegroundWindow()
$rect = New-Object RECT
[Win32]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
$sb = New-Object System.Text.StringBuilder 256
[Win32]::GetWindowText($hwnd, $sb, 256) | Out-Null
@{Left=$rect.Left; Top=$rect.Top; Width=$rect.Right-$rect.Left; Height=$rect.Bottom-$rect.Top; Title=$sb.ToString()} | ConvertTo-Json
"""],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                bounds = json.loads(result.stdout)
                with mss.MSS() as sct:
                    region = {
                        "left": max(0, bounds["Left"]),
                        "top": max(0, bounds["Top"]),
                        "width": max(100, bounds["Width"]),
                        "height": max(100, bounds["Height"]),
                    }
                    screenshot = sct.grab(region)
                    img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"window_{timestamp}.png"
                filepath = self._screenshots_dir / filename
                img.save(str(filepath), "PNG")

                self._last_capture = {
                    "path": str(filepath),
                    "width": img.width,
                    "height": img.height,
                    "window_title": bounds.get("Title", "Unknown"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                return self._last_capture
        except Exception:
            pass

        return self.capture_screen()

    def extract_text(self, image_path: str | None = None) -> str:
        """Extract text from screenshot using Windows OCR."""
        path = image_path or (self._last_capture["path"] if self._last_capture else None)
        if not path or not Path(path).exists():
            return ""

        try:
            abs_path = str(Path(path).resolve())
            result = subprocess.run(
                ["powershell", "-Command", f"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]

Function Await($WinRtTask, $ResultType) {{
    $asTask = $WinRtTask.GetType().GetMethod('AsTask', [Type[]]@())
    if ($null -eq $asTask) {{ $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{ $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }} | Select-Object -First 1 }}
    $netTask = $asTask.MakeGenericMethod($ResultType).Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}}

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync('{abs_path}')) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$ocrResult = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$ocrResult.Text
"""],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                self._last_text = result.stdout.strip()
                return self._last_text
        except Exception:
            pass

        # Fallback: basic PowerShell approach
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"(New-Object -ComObject SAPI.SpSharedRecognizer).Recognize('{path}')"],
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    def get_screen_context(self) -> str:
        """Capture screen and extract text for chat context."""
        capture = self.capture_screen()
        text = self.extract_text(capture["path"])
        return text

    def get_last_capture(self) -> dict | None:
        return self._last_capture

    def get_last_text(self) -> str:
        return self._last_text

    def cleanup_old(self, keep_last: int = 20) -> int:
        """Remove old screenshots, keep the latest N."""
        files = sorted(self._screenshots_dir.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
        removed = 0
        for f in files[keep_last:]:
            f.unlink()
            removed += 1
        return removed
