@echo off
title PD Quality Tool - Install Dependencies
echo =====================================================
echo  Postal Area Quality Check Tool
echo  Dependency Installer
echo =====================================================
echo.

cd /d "%~dp0"

REM ── Detect Python ─────────────────────────────────────────────────────────
set ARCPY=%PROGRAMFILES%\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe
set PYTHON=python

IF EXIST "%ARCPY%" (
    echo [ArcGIS Pro Python detected]
    set PYTHON=%ARCPY%
) ELSE (
    python --version >nul 2>&1
    IF ERRORLEVEL 1 (
        echo ERROR: Python not found.
        echo.
        echo Please install one of the following:
        echo   - Python 3.11+  from https://www.python.org/downloads/
        echo   - ArcGIS Pro    (includes Python automatically)
        echo.
        pause & exit /b 1
    )
    echo [System Python detected]
)

echo.
echo Installing / upgrading required packages...
echo (This may take a few minutes on first run)
echo.

"%PYTHON%" -m pip install --upgrade pip --quiet
"%PYTHON%" -m pip install -r requirements.txt

IF ERRORLEVEL 1 (
    echo.
    echo Installation failed. Try running as Administrator:
    echo   Right-click Install_Dependencies.bat ^> Run as administrator
    pause & exit /b 1
)

echo.
echo =====================================================
echo  Installation complete!
echo  Run Launch_PD_Quality_Checker.bat to start the tool
echo =====================================================
pause
