@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py"
) else (
  set "PY=python"
)

if not exist .venv (
  %PY% -m venv .venv
  if errorlevel 1 exit /b 1
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
pip install -r requirements.txt
if errorlevel 1 exit /b 1
python -m playwright install chromium
if errorlevel 1 exit /b 1
python -m unittest discover -s tests -v
if errorlevel 1 exit /b 1

echo.
echo Setup complete.
echo Run run_carousell_soft.bat or run_mudah_soft.bat for a quick soft test.
endlocal
