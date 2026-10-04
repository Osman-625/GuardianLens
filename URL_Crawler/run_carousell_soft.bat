@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  exit /b 1
)
del /q "output\carousell_urls_soft.csv" "output\carousell_summary_soft.csv" 2>nul
start "Carousell Soft Monitor" cmd /k .venv\Scripts\python.exe monitor_progress.py --site carousell --mode soft

.venv\Scripts\python.exe crawler.py --mode soft --headed
set EXITCODE=%errorlevel%
echo.
echo Primary output: output\carousell_urls_soft.csv
echo Summary: output\carousell_summary_soft.csv
pause
exit /b %EXITCODE%
