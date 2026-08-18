@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  pause
  exit /b 1
)
if not exist data\processed\metadata.json (
  echo Run prepare.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
start "" http://127.0.0.1:8000
python -m uvicorn gilching_optimizer.app:app --host 127.0.0.1 --port 8000
