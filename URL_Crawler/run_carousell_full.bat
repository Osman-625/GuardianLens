@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  exit /b 1
)
del /q "output\carousell_urls_full.csv" "output\carousell_summary_full.csv" 2>nul
start "Carousell Full Monitor" cmd /k .venv\Scripts\python.exe monitor_progress.py --site carousell --mode full

.venv\Scripts\python.exe crawler.py --mode full --headed
set EXITCODE=%errorlevel%
echo.
echo Primary output: output\carousell_urls_full.csv
echo Summary: output\carousell_summary_full.csv
pause
exit /b %EXITCODE%
