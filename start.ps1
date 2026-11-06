# Dr. Flash — One-Click Launcher
# Run this to start everything: server + UI + voice companion

$ErrorActionPreference = "SilentlyContinue"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

Write-Host ""
Write-Host "  ========================================" -ForegroundColor Cyan
Write-Host "   ⚡ Dr. Flash — Personal AI Companion" -ForegroundColor Cyan
Write-Host "  ========================================" -ForegroundColor Cyan
Write-Host ""

# Check venv
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "  [!] Setting up virtual environment..." -ForegroundColor Yellow
    python -m uv venv .venv
    python -m uv pip install -e ".[dev]" --python .venv\Scripts\python.exe
    python -m uv pip install pystray Pillow keyboard SpeechRecognition edge-tts sounddevice numpy --python .venv\Scripts\python.exe
}

# Start API server
Write-Host "  [1/3] Starting API server..." -ForegroundColor Green
$server = Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "run_server.py" `
    -WorkingDirectory $ProjectDir -WindowStyle Hidden -PassThru

# Wait for server
Write-Host "  [2/3] Waiting for server..." -ForegroundColor Green
$attempts = 0
while ($attempts -lt 20) {
    Start-Sleep -Seconds 1
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { break }
    } catch {}
    $attempts++
}
if ($attempts -ge 20) {
    Write-Host "  [!] Server failed to start" -ForegroundColor Red
} else {
    Write-Host "  [OK] Server running" -ForegroundColor Green
}

# Start frontend
Write-Host "  [3/3] Starting UI..." -ForegroundColor Green
$frontend = Start-Process -FilePath "pnpm" -ArgumentList "dev" `
    -WorkingDirectory "$ProjectDir\apps\desktop" -WindowStyle Hidden -PassThru

Write-Host ""
Write-Host "  ========================================" -ForegroundColor Cyan
Write-Host "   ⚡ Dr. Flash is READY!" -ForegroundColor Cyan
Write-Host "  ========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "   Dashboard: http://localhost:3000" -ForegroundColor White
Write-Host "   Chat:      http://localhost:3000/chat" -ForegroundColor White
Write-Host "   API:       http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host ""
Write-Host "   Say 'Dr. Flash' or press Ctrl+Alt+D" -ForegroundColor Yellow
Write-Host ""

# Start companion (system tray + voice)
& ".venv\Scripts\python.exe" companion.py
