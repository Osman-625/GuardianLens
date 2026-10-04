@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  exit /b 1
)

set SITE=%1
if "%SITE%"=="" (
  echo Which site do you want to monitor?
  echo   1. Carousell
  echo   2. Mudah
  set /p CHOICE=Enter 1 or 2:
  if "!CHOICE!"=="2" (
    set SITE=mudah
  ) else (
    set SITE=carousell
  )
)

set MODE=%2
if "%MODE%"=="" set MODE=full

.venv\Scripts\python.exe monitor_progress.py --site %SITE% --mode %MODE%
pause
