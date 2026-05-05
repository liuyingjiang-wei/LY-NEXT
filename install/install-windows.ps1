#Requires -RunAsAdministrator

function Write-Info { Write-Host "[INFO]  $args" -ForegroundColor Cyan }
function Write-Ok   { Write-Host "[OK]    $args" -ForegroundColor Green }
function Write-Warn { Write-Host "[WARN]  $args" -ForegroundColor Yellow }
function Write-Err  { Write-Host "[ERROR] $args" -ForegroundColor Red }

$os = Get-CimInstance Win32_OperatingSystem
Write-Info "OS: $($os.Caption) | $($os.OSArchitecture) | Build $($os.BuildNumber)"

$mgr = $null
if     (Get-Command winget -ErrorAction SilentlyContinue) { $mgr = "winget" }
elseif (Get-Command choco  -ErrorAction SilentlyContinue) { $mgr = "choco"  }
elseif (Get-Command scoop  -ErrorAction SilentlyContinue) { $mgr = "scoop"  }

if (-not $mgr) {
    Write-Info "No package manager found. Installing Chocolatey..."
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
    $mgr = "choco"
}
Write-Ok "Package manager: $mgr"

Write-Info "Installing Redis..."
switch ($mgr) {
    "winget" { winget install --id Redis.Redis --accept-source-agreements --accept-package-agreements --silent }
    "choco"  { choco install redis-64 -y --no-progress }
    "scoop"  { scoop install redis }
}
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
if (Get-Command redis-cli -ErrorAction SilentlyContinue) { Write-Ok "Redis installed: $(redis-cli --version)" }
else { Write-Warn "redis-cli not in PATH, restart terminal" }

Write-Info "Installing PostgreSQL..."
switch ($mgr) {
    "winget" { winget install --id PostgreSQL.PostgreSQL.16 --accept-source-agreements --accept-package-agreements --silent }
    "choco"  { choco install postgresql16 --params '/Password:postgres' -y --no-progress }
    "scoop"  { scoop install postgresql }
}
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
if (Get-Command psql -ErrorAction SilentlyContinue) { Write-Ok "PostgreSQL installed: $(psql --version)" }
else { Write-Warn "psql not in PATH. Try: C:\\Program Files\\PostgreSQL\\16\\bin" }

Write-Info "Starting services..."
$redisSvc = Get-Service -Name "Redis" -ErrorAction SilentlyContinue
if ($redisSvc) {
    if ($redisSvc.Status -ne "Running") { Start-Service "Redis" }
    Set-Service "Redis" -StartupType Automatic
    Write-Ok "Redis service: Running"
} else {
    Write-Warn "Redis service not found"
}

$pgServices = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
if ($pgServices) {
    foreach ($svc in $pgServices) {
        if ($svc.Status -ne "Running") { Start-Service $svc.Name }
        Set-Service $svc.Name -StartupType Automatic
        Write-Ok "$($svc.Name) service: Running"
    }
} else {
    Write-Warn "PostgreSQL service not found"
}

Write-Info "Connection test..."
try {
    if ((redis-cli ping 2>$null) -match "PONG") { Write-Ok "Redis: PONG" } else { Write-Warn "Redis: no response" }
} catch { Write-Warn "Redis test failed" }

try {
    $pgResult = & psql -U postgres -tAc "SELECT 1" 2>$null
    if ($pgResult) { Write-Ok "PostgreSQL: connected" } else { Write-Warn "PostgreSQL: no response" }
} catch { Write-Warn "PostgreSQL test failed" }

Write-Host ""
Write-Ok "Done."
