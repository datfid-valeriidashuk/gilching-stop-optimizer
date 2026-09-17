@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  pause
  exit /b 1
)
if not exist data\processed\demand.parquet (
  echo Run prepare.bat first. Wheelchair mode reuses the walk demand and candidates.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m gilching_optimizer.prepare --config config.yaml --wheelchair-only
if errorlevel 1 (
  echo.
  echo Wheelchair preparation failed. See the error above.
  pause
  exit /b 1
)
echo.
echo Wheelchair network is ready. Restart the app with run.bat if it is already running.
pause
