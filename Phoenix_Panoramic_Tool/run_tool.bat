@echo off
cd /d "%~dp0"
echo Installing required packages...
pip install requests pandas openpyxl psycopg2-binary xlsxwriter --quiet
echo Starting Phoenix Safety Camera Tool...
python phoenix_panoramic_tool.py
pause
