<#
.SYNOPSIS
    DARI Caregiver -- build (and optionally install) the Android APK.
.DESCRIPTION
    Command-line path, no Android Studio. Run from anywhere; paths resolve from
    this script's location.

    Steps:
      1. npm run build       with VITE_API_BASE set to -ApiBase, so the APK's baked
                             fallback points at the API host instead of 127.0.0.1
                             (which is the phone itself inside the app).
      2. npx cap sync android   copies dist/ into the native project.
      3. gradlew assembleDebug  (or assembleRelease with -Release).
      4. -Install: adb install -r onto the single connected device, then launch it.

    Prerequisites (one-time): JDK 21, Android SDK with platform 36 + build-tools,
    ANDROID_HOME (or android/local.properties with sdk.dir), adb on PATH.
    See README.md "Android app (Capacitor)".
.PARAMETER ApiBase
    API base URL baked into the build as the fallback. The in-app server sheet can
    still override it at runtime. Default: $env:DARI_API_BASE, else this PC's Tailscale
    MagicDNS name on port 8000 (stable across IP changes; tailscale ip -4 for the raw IP).
.PARAMETER Install
    After building, install onto the connected phone via adb and launch the app.
.PARAMETER Device
    adb serial or ip:port to install to when more than one device is attached.
.PARAMETER Release
    Build the release variant (needs a signing config; unsigned by default).
.PARAMETER SkipWeb
    Skip npm build + cap sync (reuse the assets already in the native project).
.EXAMPLE
    .\scripts\build_android.ps1                  # debug APK
    .\scripts\build_android.ps1 -Install         # build + adb install + launch
    .\scripts\build_android.ps1 -ApiBase http://192.168.0.232:8000 -Install   # LAN fallback
#>
param(
    [string]$ApiBase = "",
    [switch]$Install,
    [string]$Device,
    [switch]$Release,
    [switch]$SkipWeb
)

# No $ErrorActionPreference=Stop: PS 5.1 would turn native stderr (java -version, gradle warnings) into terminating errors. Exit codes are checked explicitly below.
$ROOT    = Split-Path $PSScriptRoot -Parent
$WEB     = Join-Path $ROOT "apps\caregiver_web"
$ANDROID = Join-Path $WEB  "android"
$APP_ID  = "edu.tamu.dari.caregiver"

$variant = if ($Release) { "release" } else { "debug" }
$apk     = Join-Path $ANDROID "app\build\outputs\apk\$variant\app-$variant.apk"

function Step([string]$msg) { Write-Host ""; Write-Host "  >> $msg" -ForegroundColor Cyan }
function Fail([string]$msg) { Write-Host "  !! $msg" -ForegroundColor Red; exit 1 }

# This machine's Tailscale MagicDNS name (my-pc.<tailnet-name>), or $null.
function Get-TailnetHost {
    if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) { return $null }
    try {
        $dns = (tailscale status --json | ConvertFrom-Json).Self.DNSName
        if ($dns) { return $dns.TrimEnd('.') }
    } catch {}
    return $null
}

if (-not $ApiBase) { $ApiBase = $env:DARI_API_BASE }
if (-not $ApiBase) {
    $ts = Get-TailnetHost
    if ($ts) { $ApiBase = "http://${ts}:8000" }
}
if (-not $ApiBase) { Fail "No API address: pass -ApiBase http://<host>:8000 or set DARI_API_BASE" }

# -- Toolchain sanity --------------------------------------------------------
if (-not (Get-Command java -ErrorAction SilentlyContinue)) { Fail "java not on PATH (need JDK 21)" }
$javaVer = (cmd /c "java -version 2>&1" | Select-Object -First 1)
if ($javaVer -notmatch '"21') { Write-Host "  .. java is '$javaVer' -- Capacitor 8 expects JDK 21" -ForegroundColor Yellow }
$sdkDir = $env:ANDROID_HOME
if (-not $sdkDir) {
    $lp = Join-Path $ANDROID "local.properties"
    if (Test-Path $lp) {
        $line = Get-Content $lp | Where-Object { $_ -match '^sdk\.dir=' } | Select-Object -First 1
        if ($line) { $sdkDir = ($line -replace '^sdk\.dir=', '') -replace '\\\\', '\' }
    }
}
if (-not $sdkDir -or -not (Test-Path $sdkDir)) { Fail "Android SDK not found: set ANDROID_HOME or android\local.properties sdk.dir" }

Write-Host ""
Write-Host "  DARI Caregiver -- Android $variant build" -ForegroundColor White
Write-Host "  ------------------------------------------" -ForegroundColor DarkGray
Write-Host "  API base   $ApiBase" -ForegroundColor DarkGray
Write-Host "  SDK        $sdkDir" -ForegroundColor DarkGray
Write-Host "  Java       $javaVer" -ForegroundColor DarkGray

# -- 1 + 2: web build and sync -----------------------------------------------
if (-not $SkipWeb) {
    Step "npm run build  (VITE_API_BASE=$ApiBase)"
    Push-Location $WEB
    try {
        $env:VITE_API_BASE = $ApiBase      # shell env beats .env.production.local in Vite
        & npm run build
        if ($LASTEXITCODE -ne 0) { Fail "npm run build failed" }

        Step "npx cap sync android"
        & npx cap sync android
        if ($LASTEXITCODE -ne 0) { Fail "cap sync failed" }
    } finally {
        Remove-Item Env:\VITE_API_BASE -ErrorAction SilentlyContinue
        Pop-Location
    }
}

# -- 3: gradle -----------------------------------------------------------------
$task = if ($Release) { "assembleRelease" } else { "assembleDebug" }
Step "gradlew $task"
Push-Location $ANDROID
try {
    & .\gradlew.bat $task --console=plain
    if ($LASTEXITCODE -ne 0) { Fail "gradle $task failed" }
} finally { Pop-Location }

if (-not (Test-Path $apk)) { Fail "APK not found at $apk" }
$sizeMb = [math]::Round((Get-Item $apk).Length / 1MB, 1)
Write-Host ""
Write-Host "  APK  $apk  ($sizeMb MB)" -ForegroundColor Green

# -- 4: install ----------------------------------------------------------------
if ($Install) {
    if (-not (Get-Command adb -ErrorAction SilentlyContinue)) { Fail "adb not on PATH (winget install Google.PlatformTools)" }
    Step "adb devices"
    $devices = & adb devices | Select-Object -Skip 1 | Where-Object { $_.Trim() -ne "" }
    $devices | ForEach-Object { Write-Host "     $_" -ForegroundColor DarkGray }
    # A wirelessly-debugged phone shows up twice: once as ip:port and once as an
    # "adb-XXXX._adb-tls-connect._tcp" mDNS alias. Ignore the alias so it isn't
    # counted as a second device.
    $ready = @($devices | Where-Object { $_ -match '^\S+\s+device' -and $_ -notmatch '_adb-tls-connect' })
    if ($Device) {
        $ready = @($ready | Where-Object { $_ -match ('^' + [regex]::Escape($Device) + '\s') })
        if ($ready.Count -eq 0) { Fail "device '$Device' not in adb devices" }
    }
    if ($ready.Count -eq 0) {
        if ($devices | Where-Object { $_ -match 'unauthorized' }) { Fail "phone is 'unauthorized' -- accept the USB debugging prompt on the phone and re-run" }
        Fail "no device connected (USB: enable USB debugging + File transfer mode; wireless: adb pair / adb connect first, see README)"
    }
    if ($ready.Count -gt 1) { Fail "more than one device connected; pass -Device <serial|ip:port> to pick one" }
    $serial = ($ready[0] -split '\s+')[0]
    Write-Host "  target   $serial" -ForegroundColor DarkGray

    Step "adb install -r"
    & adb -s $serial install -r $apk
    if ($LASTEXITCODE -ne 0) { Fail "adb install failed" }

    Step "launch $APP_ID"
    & adb -s $serial shell am start -n "$APP_ID/.MainActivity" | Out-Null
    Write-Host ""
    Write-Host "  Installed and launched. Logs:  adb logcat -s Capacitor/Console Capacitor" -ForegroundColor Green
}
Write-Host ""
