# Starts the GuardianLens API (port 8000) and website (port 3000).
# Run from a terminal where Guardianlens_venv is active.
param(
    [ValidateRange(1, 900)][int]$StartupTimeoutSeconds = 180,
    [switch]$ReloadApi
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $env:CONDA_PREFIX) { throw "Activate the conda environment first: conda activate Guardianlens_venv" }
$ApiPython = Join-Path $env:CONDA_PREFIX "python.exe"
if (-not (Test-Path -LiteralPath $ApiPython)) { throw "No python.exe in the active conda environment ($env:CONDA_PREFIX). Create it from environment.yml." }

function Assert-PortAvailable([int]$Port) {
    $Client = New-Object System.Net.Sockets.TcpClient
    try {
        $Connection = $Client.ConnectAsync("localhost", $Port)
        try { $Connected = $Connection.Wait(1000) -and $Client.Connected }
        catch { $Connected = $false }
        if ($Connected) { throw "Port $Port is already in use. Stop the existing server before running this launcher again." }
    }
    finally { $Client.Dispose() }
}

function Wait-DevService($Process, [string]$Url, [string]$Name, [string]$ErrorLog) {
    $Deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    while ((Get-Date) -lt $Deadline) {
        if ($Process.HasExited) { break }
        try {
            $Response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($Response.StatusCode -eq 200) { return }
        }
        catch { Start-Sleep -Milliseconds 500 }
    }
    if (Test-Path -LiteralPath $ErrorLog) { Get-Content -LiteralPath $ErrorLog -Tail 30 | Out-Host }
    throw "$Name did not become ready. Check $ErrorLog and its matching stdout log."
}

function Stop-DevProcess($Process) {
    if ($null -ne $Process -and -not $Process.HasExited) {
        # Include uvicorn's optional reload worker and npm's Next.js children.
        & "$env:SystemRoot\System32\taskkill.exe" /PID $Process.Id /T /F 2>$null | Out-Null
    }
}

Assert-PortAvailable 8000
Assert-PortAvailable 3000
$LogDir = Join-Path $Root ".tmp\dev"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$ApiErrorLog = Join-Path $LogDir "api.stderr.log"
$WebErrorLog = Join-Path $LogDir "web.stderr.log"
$ApiArguments = @("-m", "uvicorn", "api.main:app", "--host", "localhost", "--port", "8000")
# Repeated file notifications in synced folders can otherwise reload the trained models endlessly.
if ($ReloadApi) { $ApiArguments += @("--reload", "--reload-dir", "api") }
$Api = $null
$Web = $null
try {
    Write-Host "Starting GuardianLens. Trained models can take a minute to load."
    Write-Host "Startup logs: $LogDir"
    $Api = Start-Process -WindowStyle Hidden -FilePath $ApiPython -ArgumentList $ApiArguments -WorkingDirectory $Root -RedirectStandardOutput (Join-Path $LogDir "api.stdout.log") -RedirectStandardError $ApiErrorLog -PassThru
    $Web = Start-Process -WindowStyle Hidden -FilePath "npm.cmd" -ArgumentList "run", "dev" -WorkingDirectory (Join-Path $Root "frontend") -RedirectStandardOutput (Join-Path $LogDir "web.stdout.log") -RedirectStandardError $WebErrorLog -PassThru
    Wait-DevService $Api "http://localhost:8000/health" "GuardianLens API" $ApiErrorLog
    Wait-DevService $Web "http://localhost:3000" "GuardianLens website" $WebErrorLog
    Write-Host "GuardianLens API ready: http://localhost:8000"
    Write-Host "GuardianLens web ready: http://localhost:3000"
    Write-Host "Press Ctrl+C to stop both servers."
    while (-not $Api.HasExited -and -not $Web.HasExited) { Start-Sleep -Seconds 1 }
    throw "A GuardianLens server stopped. Check the logs in $LogDir."
}
finally {
    Stop-DevProcess $Api
    Stop-DevProcess $Web
}
