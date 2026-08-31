# Start the counter and restart it if it exits. Windows.
#
#   $env:SOURCE = "rtsp://user:pass@192.168.1.50:554/stream1"
#   .\run_gate.ps1
#
# The stream URL comes from the environment so real camera credentials never
# have to be written into a tracked file. Set $env:GATE too if you run more
# than one camera; each needs its own name.
#
# Watch the totals from another window with:
#   .venv\Scripts\python status.py --watch 5

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Gate = if ($env:GATE) { $env:GATE } else { "main" }
$Source = $env:SOURCE
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not $Source) {
    Write-Error "SOURCE is not set. Example:`n  `$env:SOURCE = 'rtsp://user:pass@192.168.1.50:554/stream1'`n  .\run_gate.ps1"
}

if (-not (Test-Path $Python)) {
    Write-Error "no interpreter at $Python - create the venv first:`n  python -m venv .venv`n  .venv\Scripts\python -m pip install -r requirements.txt"
}

if (-not (Test-Path (Join-Path $PSScriptRoot "lines\$Gate.json"))) {
    Write-Warning "no lines\$Gate.json. Place the counting line first:`n  .venv\Scripts\python preview.py --gate $Gate --source '$Source'"
}

while ($true) {
    & $Python count.py --gate $Gate --source $Source --no-show
    Write-Warning "gate $Gate exited, restarting in 5s"
    Start-Sleep -Seconds 5
}
