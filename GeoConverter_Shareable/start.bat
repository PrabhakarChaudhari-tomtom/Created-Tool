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
pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  [ERROR] Package installation failed.
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
