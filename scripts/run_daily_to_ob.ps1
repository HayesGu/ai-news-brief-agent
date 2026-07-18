param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$LogDir = ""
)

$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $ProjectRoot

if ([string]::IsNullOrWhiteSpace($LogDir)) {
    $LogDir = Join-Path $ProjectRoot "logs"
}

if (-not (Test-Path -LiteralPath ".\.venv\Scripts\python.exe")) {
    throw "Python virtual environment not found: $ProjectRoot\.venv"
}

if (-not (Test-Path -LiteralPath ".env")) {
    throw ".env not found: $ProjectRoot\.env"
}

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $LogDir "three_day_to_ob_$timestamp.log"
$errorLogPath = Join-Path $LogDir "three_day_to_ob_$timestamp.err.log"

$env:PYTHONPATH = "src"

$pythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$arguments = @(
    "-m",
    "ai_research_agent",
    "daily",
    "--sync-daily-kb"
)

$process = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList $arguments `
    -WorkingDirectory $ProjectRoot `
    -NoNewWindow `
    -Wait `
    -PassThru `
    -RedirectStandardOutput $logPath `
    -RedirectStandardError $errorLogPath

if ($process.ExitCode -ne 0) {
    throw "Three-day AI research briefing failed. See logs: $logPath and $errorLogPath"
}

Write-Output "Three-day AI research briefing completed. Logs: $logPath and $errorLogPath"
