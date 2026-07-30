@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  Leave Deviation App - Setup / Update
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on this PC.
    echo.
    where winget >nul 2>nul
    if errorlevel 1 (
        echo Could not find winget either, so Python can't be auto-installed.
        echo Please install Python 3.9+ manually from https://www.python.org/downloads/
        echo ^(during setup, make sure to check "Add python.exe to PATH"^).
        start https://www.python.org/downloads/
        pause
        exit /b 1
    ) else (
        echo Installing Python via winget - this may take a few minutes...
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        echo.
        echo Python installed. Please CLOSE this window, open a NEW command
        echo prompt ^(so PATH is refreshed^), and run this file again.
        pause
        exit /b 0
    )
)

echo Python found:
python --version
echo.

where winget >nul 2>nul
if not errorlevel 1 (
    echo Checking for a newer Python version via winget...
    winget upgrade -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    echo.
)

echo Upgrading pip...
python -m pip install --upgrade pip

echo.
echo Installing/updating required packages from requirements.txt...
python -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] pip install failed. Common causes: no internet access, or a
    echo corporate proxy blocking pip. Check the messages above for details.
    pause
    exit /b 1
)

echo.
echo Verifying the packages actually import correctly...
python -c "import streamlit, pandas, openpyxl, jinja2; print('streamlit', streamlit.__version__); print('pandas', pandas.__version__); print('openpyxl', openpyxl.__version__); print('jinja2', jinja2.__version__)"
if errorlevel 1 (
    echo.
    echo [ERROR] Packages were installed but cannot be imported.
    echo This usually means more than one Python is installed on this PC and
    echo pip installed to a different one than the "python" found on PATH.
    echo Try closing this window, opening a NEW command prompt, and running
    echo this file again ^(PATH may need refreshing^).
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Setup complete. You can now run run_app.bat
echo ============================================
pause
