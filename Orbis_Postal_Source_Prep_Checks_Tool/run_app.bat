@echo off
REM Launches the Orbis Postal Area Source Preparation Checks tool (Streamlit app).
REM Preferred port 8520 - if taken (e.g. a second instance of this same
REM tool), automatically tries the next free port instead.
setlocal enabledelayedexpansion
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on PATH. Install Python and try again.
    pause
    exit /b 1
)

python -c "import streamlit, geopandas, openpyxl" >nul 2>nul
if errorlevel 1 (
    echo Installing required packages...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Failed to install dependencies.
        pause
        exit /b 1
    )
)

set BASEPORT=8520
for /f %%P in ('powershell -NoProfile -Command "$p=%BASEPORT%; while(Test-NetConnection -ComputerName localhost -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue){$p++}; Write-Output $p"') do set PORT=%%P

echo Starting Orbis Postal Area Source Preparation Checks tool on http://localhost:!PORT! ...
python -m streamlit run app.py --server.port !PORT!

endlocal
