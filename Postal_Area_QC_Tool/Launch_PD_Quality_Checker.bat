@echo off
title Postal Area Quality Check Tool

cd /d "%~dp0"

REM ── Try ArcGIS Pro Python first (has geopandas/shapely built in) ──────────
set ARCPY=%PROGRAMFILES%\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe
set PYTHON=python

IF EXIST "%ARCPY%" (
    echo Using ArcGIS Pro Python...
    set PYTHON=%ARCPY%
) ELSE (
    echo ArcGIS Pro Python not found. Using system Python...
    python --version >nul 2>&1
    IF ERRORLEVEL 1 (
        echo ERROR: Python not found. Install Python 3.11+ or ArcGIS Pro.
        pause & exit /b 1
    )
)

REM ── Install / update dependencies ─────────────────────────────────────────
echo Checking dependencies...
"%PYTHON%" -m pip install -q -r requirements.txt

REM ── Launch Streamlit ───────────────────────────────────────────────────────
echo Starting Postal Area Quality Check Tool...
start "PD_QC_Server" "%PYTHON%" -m streamlit run app.py --server.port 8503 --server.headless true --browser.gatherUsageStats false

echo Waiting for server to start (15 seconds)...
timeout /t 15 /nobreak >nul

start "" "http://localhost:8503"

echo.
echo Postal Area Quality Check Tool is running at http://localhost:8503
echo Close this window to stop the tool.
echo.
pause
