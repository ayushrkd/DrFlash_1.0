@echo off
title Dr. Flash - Starting...
color 0B
echo.
echo  ========================================
echo   Dr. Flash - Personal AI Companion
echo  ========================================
echo.

cd /d "%~dp0"

:: Check if venv exists
if not exist ".venv\Scripts\python.exe" (
    echo  [!] Setting up virtual environment...
    python -m uv venv .venv
    python -m uv pip install -e ".[dev]" --python .venv\Scripts\python.exe
    python -m uv pip install pystray Pillow keyboard SpeechRecognition edge-tts sounddevice numpy --python .venv\Scripts\python.exe
    python -m uv pip install faster-whisper piper-tts soundfile pywinauto browser-use playwright --python .venv\Scripts\python.exe
    .venv\Scripts\playwright.exe install chromium
)

:: Check Piper model
if not exist "data\models\piper\en_US-lessac-medium.onnx" (
    echo  [!] Downloading Piper TTS voice model...
    .venv\Scripts\python.exe -c "import httpx,os;os.makedirs('data/models/piper',exist_ok=True);[open(f'data/models/piper/{f}','wb').write(httpx.Client(timeout=120,follow_redirects=True).get(f'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/{f}').content) for f in ['en_US-lessac-medium.onnx','en_US-lessac-medium.onnx.json']];print('  Done')"
)

:: Check Vosk model
if not exist "data\models\vosk-small" (
    echo  [!] Downloading Vosk wake word model...
    .venv\Scripts\python.exe -c "from vosk import Model;import os,urllib.request,zipfile;os.makedirs('data/models',exist_ok=True);urllib.request.urlretrieve('https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip','data/models/v.zip');zipfile.ZipFile('data/models/v.zip').extractall('data/models/');os.rename([d for d in os.listdir('data/models') if d.startswith('vosk-model')][0],'data/models/vosk-small');os.remove('data/models/v.zip');print('  Done')"
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
echo   Dr. Flash is READY!
echo  ========================================
echo.
echo   Dashboard: http://localhost:7828
echo   Chat:      http://localhost:7828/chat
echo   API:       http://127.0.0.1:7827/docs
echo.
echo   Say "Dr. Flash" or press Ctrl+Alt+D
echo.
echo   Voice: faster-whisper (GPU) + Piper TTS
echo   Tools: 12 registered (browser, windows, files, code, meetings...)
echo.

:: Start the companion (system tray + voice)
".venv\Scripts\python.exe" companion.py
