@echo off
title AA1 Name Checker - Install & Launch

REM ── Configuration ─────────────────────────────────────────────────────────
set REPO_URL=https://github.com/PrabhakarChaudhari-tomtom/Created-Tool.git
set INSTALL_DIR=%USERPROFILE%\AA1_Name_Checker
set PORT=8502

echo ============================================================
echo   AA1 Name Checker - Installer
echo   ADP Team, TomTom
echo ============================================================
echo.

REM ── Check Python ──────────────────────────────────────────────────────────
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Python not found.
    echo Please install Python 3.11 or 3.12 from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
echo [OK] Python found.

REM ── Check Git ─────────────────────────────────────────────────────────────
git --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Git not found.
    echo Please install Git from https://git-scm.com/download/win
    pause
    exit /b 1
)
echo [OK] Git found.

REM ── Clone or update repo ──────────────────────────────────────────────────
IF EXIST "%INSTALL_DIR%\.git" (
    echo.
    echo [INFO] Existing installation found. Updating to latest version...
    cd /d "%INSTALL_DIR%"
    git pull origin main
    IF ERRORLEVEL 1 (
        echo [ERROR] Git pull failed. Check your internet connection.
        pause
        exit /b 1
    )
    echo [OK] Updated to latest version.
) ELSE (
    echo.
    echo [INFO] Downloading AA1 Name Checker from GitHub...
    git clone "%REPO_URL%" "%INSTALL_DIR%"
    IF ERRORLEVEL 1 (
        echo [ERROR] Download failed. Check your internet connection and GitHub access.
        pause
        exit /b 1
    )
    echo [OK] Download complete.
)

REM ── Install dependencies ───────────────────────────────────────────────────
echo.
echo [INFO] Installing / updating Python dependencies...
cd /d "%INSTALL_DIR%"
pip install -q -r requirements.txt
IF ERRORLEVEL 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo [OK] Dependencies ready.

REM ── Launch tool ────────────────────────────────────────────────────────────
echo.
echo [INFO] Starting AA1 Name Checker on port %PORT%...
start /b python -m streamlit run app.py --server.port %PORT% --server.headless true --browser.gatherUsageStats false

echo [INFO] Waiting for server to start...
timeout /t 5 /nobreak >nul

start "" "http://localhost:%PORT%"

echo.
echo ============================================================
echo   AA1 Name Checker is running at http://localhost:%PORT%
echo   Installation folder: %INSTALL_DIR%
echo   Close this window to stop the tool.
echo ============================================================
echo.
pause
