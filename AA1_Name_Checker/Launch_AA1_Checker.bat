@echo off
title AA1 Name Checker

REM ── Change to the tool folder ─────────────────────────────────────────────
cd /d "%~dp0"

REM ── Check Python is available ─────────────────────────────────────────────
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo ERROR: Python not found. Please install Python 3.11 or 3.12.
    pause
    exit /b 1
)

REM ── Install dependencies if needed ────────────────────────────────────────
echo Checking dependencies...
pip install -q -r requirements.txt

REM ── Start Streamlit in the background ────────────────────────────────────
echo Starting AA1 Name Checker...
start /b python -m streamlit run app.py --server.port 8502 --server.headless true --browser.gatherUsageStats false

REM ── Wait for Streamlit to start ───────────────────────────────────────────
echo Waiting for server to start...
timeout /t 4 /nobreak >nul

REM ── Open in browser (tries Edge first, then default browser) ─────────────
start "" "http://localhost:8502"

echo.
echo AA1 Name Checker is running at http://localhost:8502
echo Close this window to stop the tool.
echo.
pause
