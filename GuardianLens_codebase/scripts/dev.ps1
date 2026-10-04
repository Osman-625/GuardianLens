$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Api = Start-Process -FilePath "python" -ArgumentList "-m", "uvicorn", "api.main:app", "--reload", "--port", "8000" -WorkingDirectory $Root -PassThru
$Web = Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev" -WorkingDirectory (Join-Path $Root "frontend") -PassThru
Write-Host "GuardianLens API: http://localhost:8000"
Write-Host "GuardianLens web: http://localhost:3000"
Write-Host "Press Ctrl+C, then stop process IDs $($Api.Id) and $($Web.Id) if they remain running."
Wait-Process -Id $Api.Id, $Web.Id
