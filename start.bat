@echo off
title Dr. Flash - Starting...
color 0B
echo.
echo  ========================================
echo   ⚡ Dr. Flash - Personal AI Companion
echo  ========================================
echo.

cd /d "%~dp0"

:: Check if venv exists
if not exist ".venv\Scripts\python.exe" (
    echo  [!] Virtual environment not found. Setting up...
    python -m uv venv .venv
    python -m uv pip install -e ".[dev]" --python .venv\Scripts\python.exe
    python -m uv pip install pystray Pillow keyboard SpeechRecognition edge-tts sounddevice numpy --python .venv\Scripts\python.exe
)

:: Start the API server in background
echo  [1/3] Starting API server...
start /B /MIN "" ".venv\Scripts\python.exe" run_server.py

:: Wait for server
echo  [2/3] Waiting for server...
:wait_server
timeout /t 1 /nobreak >nul
curl -s http://127.0.0.1:7827/health >nul 2>&1
if errorlevel 1 goto wait_server
echo  [OK] Server is running

:: Start frontend in background
echo  [3/3] Starting UI...
cd apps\desktop
start /B /MIN "" pnpm dev
cd ..\..

echo.
echo  ========================================
echo   ⚡ Dr. Flash is READY!
echo  ========================================
echo.
echo   Dashboard: http://localhost:7828
echo   Chat:      http://localhost:7828/chat
echo   API:       http://127.0.0.1:7827/docs
echo.
echo   Say "Dr. Flash" or press Ctrl+Alt+D
echo.

:: Start the companion (system tray + voice)
".venv\Scripts\python.exe" companion.py
