@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  exit /b 1
)
del /q "output\mudah_urls_soft.csv" "output\mudah_summary_soft.csv" 2>nul
start "Mudah Soft Monitor" cmd /k .venv\Scripts\python.exe monitor_progress.py --site mudah --mode soft

.venv\Scripts\python.exe crawler.py --site mudah --mode soft --headed
set EXITCODE=%errorlevel%
echo.
echo Primary output: output\mudah_urls_soft.csv
echo Summary: output\mudah_summary_soft.csv
pause
exit /b %EXITCODE%
