<#
.SYNOPSIS
    DARI Smart Homecare -- Service Launcher
.DESCRIPTION
    Starts all 4 DARI services in one terminal, similar to docker compose up.
    Run from the repo root.

    Every service always binds the same fixed port (API :8000, Caregiver App :5173).
    Starting always kills whatever's already there first -- by port for the two
    services that bind one, and by command-line match for the two that don't
    (dari.activity_engine.engine / dari.rule_engine.engine) -- so a crashed terminal, a
    closed window, or a previous run you forgot to stop can never leave orphaned
    processes squatting on a port or silently piling up in the background. This
    checks the live process list every time rather than trusting a saved PID
    file, so it catches stragglers no matter how they were started.
.PARAMETER Stop
    Kill all running DARI services.
.PARAMETER Status
    Show whether each service is currently running.
.PARAMETER SkipEngine
    On start, don't (re)start the activity engine.
.PARAMETER SkipRuleEngine
    On start, don't (re)start the rule engine.
.PARAMETER SkipApp
    On start, don't (re)start the caregiver app dev server.
.EXAMPLE
    .\launch.ps1           # stop anything stale, then start all services fresh
    .\launch.ps1 -Stop     # stop all services
    .\launch.ps1 -Status   # check which are running
#>
param(
    [switch]$Stop,
    [switch]$Status,
    [switch]$SkipEngine,
    [switch]$SkipRuleEngine,
    [switch]$SkipApp
)

$ROOT  = $PSScriptRoot
# conda: $env:CONDA_EXE (set by conda init), else whatever `conda` is on PATH, else the
# default per-user Anaconda location.
$CONDA = if ($env:CONDA_EXE) { $env:CONDA_EXE }
         elseif (Get-Command conda -ErrorAction SilentlyContinue) { (Get-Command conda).Source }
         else { Join-Path $env:USERPROFILE "anaconda3\Scripts\conda.exe" }

# This machine's Tailscale MagicDNS name (my-pc.<tailnet-name>), or $null.
function Get-TailnetHost {
    if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) { return $null }
    try {
        $dns = (tailscale status --json | ConvertFrom-Json).Self.DNSName
        if ($dns) { return $dns.TrimEnd('.') }
    } catch {}
    return $null
}


# ---------------------------------------------------------------------------
# Service definitions
#   Port    -- fixed port this service must always bind (checked + freed before start)
#   Pattern -- command-line substring to match for services that don't bind a port
# ---------------------------------------------------------------------------
$SERVICES = @(
    @{
        # Pattern (not just Port) matters here: --reload runs an outer reloader process
        # that doesn't bind the port itself, plus a worker that does. Killing only the
        # port's listener leaves the reloader alive, and it immediately respawns a new
        # worker -- Port alone can never actually stop this service.
        Label   = "DARI API"
        Color   = "Cyan"
        Port    = 8000
        Pattern = 'uvicorn.*dari\.api_server\.main:app'
        RunCmd  = "& '$CONDA' run -n LLMs python -m uvicorn dari.api_server.main:app --host 0.0.0.0 --port 8000 --reload"
    },
    @{
        Label   = "DARI Activity Engine"
        Color   = "Green"
        Pattern = 'dari\.activity_engine\.engine'
        RunCmd  = "& '$CONDA' run -n LLMs python -m dari.activity_engine.engine --profile config/profiles/patient_001.yaml"
    },
    @{
        Label   = "DARI Rule Engine"
        Color   = "Yellow"
        Pattern = 'dari\.rule_engine\.engine'
        RunCmd  = "& '$CONDA' run -n LLMs python -m dari.rule_engine.engine --profile config/profiles/patient_001.yaml"
    },
    @{
        # Pattern here too: npm wraps a chain of cmd.exe/node.exe processes down to the
        # actual vite dev server. Port-only killing hits the listener but can leave
        # intermediate wrapper processes as orphans.
        Label   = "DARI Caregiver App"
        Color   = "Magenta"
        Port    = 5173
        Pattern = 'vite'
        Url     = "http://localhost:5173"
        RunCmd  = "npm --prefix apps/caregiver_web run dev"
    }
)

# ---------------------------------------------------------------------------
# Live-state helpers -- always query the real process list, never a saved file
# ---------------------------------------------------------------------------

function Get-PortPids([int]$Port) {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
}

function Get-PatternPids([string]$Pattern) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $Pattern } |
        Select-Object -ExpandProperty ProcessId
}

function Get-ServicePids($svc) {
    # Union both -- a service can have a live port-listener AND unrelated wrapper/
    # supervisor processes that never show up in a port lookup (see comments above).
    $found = @()
    if ($svc.Port)    { $found += Get-PortPids -Port $svc.Port }
    if ($svc.Pattern) { $found += Get-PatternPids -Pattern $svc.Pattern }
    return @($found | Select-Object -Unique)
}

function Stop-ServiceProcesses($svc) {
    $stopped = 0
    foreach ($p in (Get-ServicePids $svc)) {
        try {
            Stop-Process -Id $p -Force -ErrorAction Stop
            Write-Host "  Stopped  $($svc.Label)  (PID $p)" -ForegroundColor DarkGray
            $stopped++
        } catch { }
    }
    return $stopped
}

function Show-Status {
    Write-Host ""
    Write-Host "  DARI Service Status" -ForegroundColor White
    Write-Host "  -------------------------------------" -ForegroundColor DarkGray
    foreach ($svc in $SERVICES) {
        $svcPids = Get-ServicePids $svc
        if ($svcPids.Count -gt 0) {
            $pidList = ($svcPids -join ", ")
            Write-Host "  [ON]  $($svc.Label)" -ForegroundColor Green -NoNewline
            Write-Host "  (PID $pidList)" -ForegroundColor DarkGray
        } else {
            Write-Host "  [--]  $($svc.Label)" -ForegroundColor DarkGray
        }
    }
    Write-Host ""
}

function Stop-AllServices {
    Write-Host ""
    Write-Host "  Stopping DARI services..." -ForegroundColor Yellow
    $killed = 0
    foreach ($svc in $SERVICES) {
        $killed += Stop-ServiceProcesses $svc
    }
    if ($killed -eq 0) {
        Write-Host "  No DARI processes found running." -ForegroundColor DarkGray
    } else {
        Write-Host "  Stopped $killed process(es)." -ForegroundColor Yellow
    }
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Launch functions
# ---------------------------------------------------------------------------

function Start-ServiceProcess($svc) {
    $startArgs = @{
        FilePath         = "powershell.exe"
        ArgumentList     = @("-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $svc.RunCmd)
        WorkingDirectory = $ROOT
        WindowStyle      = "Hidden"
        PassThru         = $true
    }
    $proc = Start-Process @startArgs
    [pscustomobject]@{ Service = $svc; Process = $proc }
}

# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

if ($Stop) {
    Stop-AllServices
    exit
}

if ($Status) {
    Show-Status
    exit
}

# -- Start all ------------------------------------------------------------
# Always kill whatever's currently running for each service being (re)started,
# by port / command-line match -- not by a saved PID file -- so this is safe
# and idempotent to run repeatedly, however previous runs were left behind.

Write-Host ""
Write-Host "  DARI Smart Homecare -- Starting services" -ForegroundColor White
Write-Host "  ------------------------------------------" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Stopping stagnant processes..." -ForegroundColor Yellow

$skipMap = @{
    "DARI Activity Engine" = $SkipEngine
    "DARI Rule Engine"     = $SkipRuleEngine
    "DARI Caregiver App"   = $SkipApp
}

foreach ($svc in $SERVICES) {
    if ($skipMap.ContainsKey($svc.Label) -and $skipMap[$svc.Label]) { continue }
    Stop-ServiceProcesses $svc | Out-Null
}

Write-Host ""

foreach ($svc in $SERVICES) {
    if ($skipMap.ContainsKey($svc.Label) -and $skipMap[$svc.Label]) {
        Write-Host "  ..  $($svc.Label)  skipped" -ForegroundColor DarkGray
        continue
    }
    Write-Host "  >> $($svc.Label)" -ForegroundColor $svc.Color -NoNewline
    $state = Start-ServiceProcess $svc
    Write-Host "   started (PID $($state.Process.Id))" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "  URLs" -ForegroundColor White
Write-Host "  ------------------------------------------" -ForegroundColor DarkGray
Write-Host "  API docs       http://127.0.0.1:8000/docs" -ForegroundColor Cyan
$tsHost = Get-TailnetHost
if ($tsHost) {
    Write-Host "  API (phone)    http://${tsHost}:8000   (tailnet; the API binds 0.0.0.0)" -ForegroundColor Cyan
}
Write-Host "  Caregiver app  http://localhost:5173" -ForegroundColor Magenta
Write-Host "  Admin panel    http://localhost:5173?mode=admin" -ForegroundColor Magenta
Write-Host ""
Write-Host "  .\launch.ps1 -Status   check running services" -ForegroundColor DarkGray
Write-Host "  .\launch.ps1 -Stop     kill all DARI processes" -ForegroundColor DarkGray
Write-Host ""

Start-Sleep -Seconds 2
Show-Status
