@echo off
REM ============================================================
REM Treasury Dashboard - one-time setup for Windows
REM Run this from inside the project folder
REM ============================================================

echo.
echo === Treasury Dashboard Setup ===
echo.

REM Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not on PATH.
    echo Install Python 3.11+ from python.org and check "Add to PATH".
    pause
    exit /b 1
)

REM Create virtual environment
if not exist venv\ (
    echo Creating virtual environment...
    python -m venv venv
) else (
    echo Virtual environment already exists - skipping.
)

REM Activate it
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip --quiet

REM Install requirements
echo Installing dependencies (this takes ~2 min)...
pip install -r requirements.txt

REM Copy .env if missing
if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo.
        echo === IMPORTANT ===
        echo A .env file was created from .env.example.
        echo Open it in Notepad and add your real FRED_API_KEY and SEC_USER_AGENT.
        echo   notepad .env
        echo.
    )
)

echo.
echo === Setup complete! ===
echo.
echo Next steps:
echo   1. notepad .env       (add your API key and email)
echo   2. run_tests.bat      (verify everything works)
echo.
pause
