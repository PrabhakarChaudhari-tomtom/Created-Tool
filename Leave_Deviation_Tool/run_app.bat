@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH.
    echo Run install_requirements.bat first to install Python and the required packages.
    pause
    exit /b 1
)

echo Checking required packages (streamlit, pandas, openpyxl, jinja2)...
python -c "import streamlit, pandas, openpyxl, jinja2" >nul 2>nul
if errorlevel 1 (
    echo Packages missing or incomplete - installing now, this can take a minute...
    python -m pip install -r requirements.txt
    python -c "import streamlit, pandas, openpyxl, jinja2" >nul 2>nul
    if errorlevel 1 (
        echo.
        echo [ERROR] streamlit/pandas/openpyxl/jinja2 still cannot be imported after install.
        echo This usually means multiple Python installs exist on this PC and pip
        echo installed to a different one than the "python" on PATH.
        echo Try: python -m pip install --user -r requirements.txt
        pause
        exit /b 1
    )
)
echo Packages OK.

echo.
echo Launching the Leave Deviation app in a new window...
start "Leave Deviation App - Server" cmd /k python -m streamlit run app.py --server.port 8502

echo Waiting for the app to start, then opening your browser...
timeout /t 5 /nobreak >nul
start "" http://localhost:8502

echo.
echo If a browser tab did not open, go to http://localhost:8502 manually.
echo The app keeps running in the other window titled "Leave Deviation App - Server" - close that window to stop it.
echo This window can be closed now.
pause
