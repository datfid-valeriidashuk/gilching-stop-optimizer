@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m gilching_optimizer.prepare --config config.yaml
if errorlevel 1 (
  echo.
  echo Preparation failed. See the error above.
  pause
  exit /b 1
)
echo.
echo Data preparation complete. Now run run.bat.
pause
