# One-time setup: creates a virtual environment OUTSIDE OneDrive and installs requirements.
$venv = Join-Path $env:USERPROFILE 'venvs\guardianlens'
if (-not (Test-Path $venv)) { python -m venv $venv --system-site-packages }
& "$venv\Scripts\python.exe" -m pip install -r "$PSScriptRoot\requirements.txt"
Write-Host "`nReady. Run:  & '$venv\Scripts\python.exe' -m gl all"
