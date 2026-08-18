@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher "py" was not found.
  echo Install Python 3.12 from https://www.python.org/downloads/ and enable the launcher.
  pause
  exit /b 1
)
if not exist .venv (
  py -3.12 -m venv .venv
  if errorlevel 1 (
    echo Could not create Python 3.12 environment. Make sure Python 3.12 is installed.
    pause
    exit /b 1
  )
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)
echo.
echo Setup complete. Next run prepare.bat once.
pause
