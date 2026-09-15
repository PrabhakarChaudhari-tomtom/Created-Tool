@echo off
title Geospatial Format Converter - ADP Team, TomTom
color 0A

echo.
echo  ============================================================
echo   Geospatial Format Converter - ADP Team, TomTom
echo  ============================================================
echo.

:: ── Step 1: Install dependencies ─────────────────────────────────────────────
echo  [1/2] Installing required packages...

where pip >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] 'pip' was not found on this machine.
    echo  This means Python isn't installed, or was installed without being
    echo  added to PATH. Please install Python 3.11 or 3.12 from
    echo  https://www.python.org/downloads/ and tick "Add Python to PATH"
    echo  on the first installer screen, then run start.bat again.
    echo  Please contact ADP team: prabhakar.chaudhari@tomtom.com
    pause
    exit /b 1
)

pip install -r requirements.txt --quiet --disable-pip-version-check --timeout 120 --retries 10
if errorlevel 1 (
    echo.
    echo  [ERROR] Package installation failed.
    echo  If you saw a "Read timed out" warning above, your network/proxy is
    echo  too slow or slow to reach pypi.org - try again on a faster/wired
    echo  connection, or ask IT about an internal PyPI mirror.
    echo  Please contact ADP team: prabhakar.chaudhari@tomtom.com
    pause
    exit /b 1
)
echo  [OK] Packages ready.
echo.

:: ── Step 2: Launch the tool ───────────────────────────────────────────────────
echo  [2/2] Launching Geospatial Format Converter...
echo.
echo  The tool will open in your browser automatically.
echo  Keep this window open while using the tool.
echo  Close this window to stop the tool.
echo.
echo  ============================================================
echo.
streamlit run app.py --server.headless false
pause
