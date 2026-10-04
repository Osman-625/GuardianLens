@echo off
setlocal
where conda >nul 2>nul || (echo ERROR: Conda was not found.& exit /b 1)
call conda run --no-capture-output -n guardianlens-collector python -u main.py
