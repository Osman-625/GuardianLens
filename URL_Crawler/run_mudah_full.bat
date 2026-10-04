@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  exit /b 1
)
del /q "output\mudah_urls_full.csv" "output\mudah_summary_full.csv" 2>nul
start "Mudah Full Monitor" cmd /k .venv\Scripts\python.exe monitor_progress.py --site mudah --mode full

.venv\Scripts\python.exe crawler.py --site mudah --mode full --headed
set EXITCODE=%errorlevel%
echo.
echo Primary output: output\mudah_urls_full.csv
echo Summary: output\mudah_summary_full.csv
pause
exit /b %EXITCODE%
