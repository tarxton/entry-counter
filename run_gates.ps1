# Start one counter process per gate and keep each alive.
#
# Edit $Gates below with the real RTSP URLs, then:
#   .\run_gates.ps1
#
# Each gate runs in its own window so one camera dying cannot take the other
# down, and you can restart a single gate without touching the other. Counts
# live in data/events_<gate>.csv, so a restart resumes without losing anything.
#
# Watch the totals from a separate window with:
#   .venv\Scripts\python status.py --watch 5

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Gates = @(
    @{ Name = "north"; Source = "rtsp://user:pass@192.168.1.50:554/stream" },
    @{ Name = "south"; Source = "rtsp://user:pass@192.168.1.51:554/stream" }
)

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "venv not found at $Python" }

foreach ($gate in $Gates) {
    $name = $gate.Name
    if (-not (Test-Path (Join-Path $PSScriptRoot "lines\$name.json"))) {
        Write-Warning "no lines\$name.json - run: .venv\Scripts\python preview.py --gate $name --source '$($gate.Source)'"
    }

    # -NoExit keeps the window open on crash so the traceback is readable.
    # The inner loop restarts the counter if it exits for any reason.
    $inner = "while (`$true) { & '$Python' count.py --gate $name --source '$($gate.Source)' --no-show; " +
             "Write-Warning 'gate $name exited, restarting in 5s'; Start-Sleep -Seconds 5 }"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $inner
    Write-Host "started gate $name"
}

Write-Host ""
Write-Host "All gates started. Totals: .venv\Scripts\python status.py --watch 5"
