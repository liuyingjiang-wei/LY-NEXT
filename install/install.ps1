param(
    [switch]$Redis,
    [switch]$PostgreSQL,
    [switch]$Pgvector,
    [switch]$All,
    [switch]$DetectOnly,
    [switch]$ConfigureOnly,
    [switch]$Force,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$script:LyNextInstalledPgPassword = $null
. (Join-Path $ScriptDir "pg-common.ps1")

function Write-Info { param([string]$Message) Write-Host "[INFO]  $Message" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Message) Write-Host "[OK]    $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "[WARN]  $Message" -ForegroundColor Yellow }

function Assert-LyNextAdmin {
    param([string]$Reason = "安装或启动 Windows 服务")
    if (Test-PgCommonWindowsAdmin) { return }
    Write-Warn "需要管理员权限 ($Reason)"
    Write-Warn "请右键 PowerShell, 以管理员身份运行, 在项目根目录执行: ..\install.ps1"
    exit 1
}

function Get-LyNextRedisStatus {
    $cli = Get-Command redis-cli -ErrorAction SilentlyContinue
    $svc = Get-Service -Name "Redis" -ErrorAction SilentlyContinue
    $version = $null
    $reachable = $false
    if ($cli) {
        try { $version = (& redis-cli --version 2>$null).ToString().Trim() } catch { }
        try { $reachable = ((& redis-cli ping 2>$null) -match "PONG") } catch { }
    }
    [pscustomobject]@{
        Key = "redis"; Name = "Redis"; Installed = [bool]($cli -or $svc)
        Version = $version; Service = if ($svc) { $svc.Status.ToString() } else { $null }; Reachable = $reachable
    }
}

function Get-LyNextPostgreSQLStatus {
    $serviceNames = Get-PgCommonWindowsPostgresServices
    $serviceStr = $null
    if ($serviceNames.Count -gt 0) {
        $serviceStr = ($serviceNames | ForEach-Object {
                $s = Get-Service -Name $_ -ErrorAction SilentlyContinue
                if ($s) { "$($s.Name):$($s.Status)" }
            }) -join "; "
    }

    $hit = Resolve-PgCommonPsqlExe
    $version = $null
    $reachable = $false
    $extra = @()
    $dbCfg = Read-PgCommonLyNextDatabaseConfig -RepoRoot $RepoRoot

    if ($hit) {
        try { $version = (& $hit.Path --version 2>$null).ToString().Trim() } catch { }
        $port = if ($dbCfg.port -gt 0) { $dbCfg.port } else { (Read-PgCommonPostgresPort -PgRoot $hit.Root) }
        $extra += "port $port"
        foreach ($h in @("127.0.0.1", "localhost")) {
            if (-not (Test-PgCommonTcpPort -HostName $h -Port $port)) { continue }
            if (Invoke-PgCommonPsql -Psql $hit.Path -DbHost $h -Port $port -Username $dbCfg.username `
                    -Password $dbCfg.password -Database "postgres" -Sql "SELECT 1" -Quiet) {
                $reachable = $true
                $extra += "ok"
                break
            }
        }
        if (-not $reachable -and $serviceStr) {
            $extra += "port closed (Start-Service postgresql-x64-*)"
        }
    }

    [pscustomobject]@{
        Key = "postgresql"; Name = "PostgreSQL"
        Installed = [bool]($hit -or $serviceNames.Count -gt 0)
        Version = if ($version) { $version } else { ($extra -join ", ") }
        Service = $serviceStr
        Reachable = $reachable
    }
}

function Get-LyNextPgvectorStatus {
    $hit = Resolve-PgCommonPsqlExe
    $vectorCtl = if ($hit) { Get-PgCommonVectorControlPath -PgRoot $hit.Root } else { $null }
    $extensionOk = $false
    $detail = if ($vectorCtl) { "vector.control OK" } else { $null }
    $dbCfg = Read-PgCommonLyNextDatabaseConfig -RepoRoot $RepoRoot

    if ($hit) {
        $port = if ($dbCfg.port -gt 0) { $dbCfg.port } else { (Read-PgCommonPostgresPort -PgRoot $hit.Root) }
        foreach ($h in @("127.0.0.1", "localhost")) {
            if (-not (Test-PgCommonTcpPort -HostName $h -Port $port)) { continue }
            if (Test-PgCommonPgvectorInDatabase -Psql $hit.Path -DbHost $h -Port $port `
                    -Username $dbCfg.username -Password $dbCfg.password -Database $dbCfg.database) {
                $extensionOk = $true
                $detail = "ly_next.vector"
                break
            }
        }
        if (-not $extensionOk -and $vectorCtl) {
            if (Test-PgCommonTcpPort -HostName "127.0.0.1" -Port $port) {
                $detail = "files OK; run CREATE EXTENSION or set database.password"
            } else {
                $detail = "files OK; port $port not listening"
            }
        } elseif (-not $extensionOk) {
            $detail = "missing vector.control (needs build)"
        }
    } elseif (-not $vectorCtl) {
        $detail = "needs PostgreSQL"
    }

    [pscustomobject]@{
        Key = "pgvector"; Name = "pgvector"; Installed = $extensionOk
        Version = $detail; Service = $null; Reachable = $extensionOk
    }
}

function Get-LyNextInstallStatus {
    [pscustomobject]@{
        Redis = Get-LyNextRedisStatus
        PostgreSQL = Get-LyNextPostgreSQLStatus
        Pgvector = Get-LyNextPgvectorStatus
    }
}

function Show-LyNextInstallStatus {
    param([object]$Status = (Get-LyNextInstallStatus))
    Write-Host ""
    Write-Host "=== LY-NEXT 依赖环境 ===" -ForegroundColor Cyan
    foreach ($key in @("Redis", "PostgreSQL", "Pgvector")) {
        $c = $Status.$key
        $ready = if ($key -eq "Pgvector") { $c.Reachable } elseif ($key -eq "Redis") { $c.Reachable } else { $c.Installed }
        $tag = if ($ready) { "[已就绪]" } else { "[未就绪]" }
        $color = if ($ready) { "Green" } else { "Yellow" }
        $extra = @()
        if ($c.Version) { $extra += $c.Version }
        if ($c.Service) { $extra += $c.Service }
        if ($c.Reachable) { $extra += "可连接" }
        $suffix = if ($extra.Count -gt 0) { " - " + ($extra -join ', ') } else { "" }
        Write-Host ("  {0,-12} {1}{2}" -f $c.Name, $tag, $suffix) -ForegroundColor $color
    }
    Write-Host ""
}

function Test-LyNextComponentSatisfied {
    param([string]$Component, [object]$Status)
    switch ($Component.ToLowerInvariant()) {
        "redis" { return $Status.Redis.Reachable }
        "postgresql" { return $Status.PostgreSQL.Installed }
        "pgvector" { return $Status.Pgvector.Reachable }
        default { return $false }
    }
}

function Get-LyNextMissingComponents {
    param([object]$Status)
    $m = @()
    if (-not $Status.Redis.Reachable) { $m += "redis" }
    if (-not $Status.PostgreSQL.Installed) { $m += "postgresql" }
    if (-not $Status.Pgvector.Reachable) { $m += "pgvector" }
    return $m
}

function Refresh-PathEnv {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Ensure-PackageManager {
    if (Get-Command winget -ErrorAction SilentlyContinue) { return "winget" }
    if (Get-Command choco  -ErrorAction SilentlyContinue) { return "choco"  }
    if (Get-Command scoop  -ErrorAction SilentlyContinue) { return "scoop"  }
    Write-Info "Installing Chocolatey..."
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    Refresh-PathEnv
    if (Get-Command choco -ErrorAction SilentlyContinue) { return "choco" }
    throw "No package manager available"
}

function Install-LyNextRedis {
    param([string]$Manager)
    Write-Info "Installing Redis..."
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        switch ($Manager) {
            "winget" { winget install --id Redis.Redis --accept-source-agreements --accept-package-agreements --silent }
            "choco"  { choco install redis-64 -y --no-progress }
            "scoop"  { scoop install redis }
        }
    } catch {
        Write-Warn "Redis install warning (may already installed): $($_.Exception.Message)"
    } finally {
        $ErrorActionPreference = $prevEap
    }
    Refresh-PathEnv
}

function Install-LyNextPostgreSQL {
    param([string]$Manager)
    Write-Info "Installing PostgreSQL 17..."
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        switch ($Manager) {
            "winget" {
                Write-Warn "winget PostgreSQL: set postgres password in installer; script tries password postgres or prompts you"
                winget install --id PostgreSQL.PostgreSQL.17 --accept-source-agreements --accept-package-agreements --silent
                $script:LyNextInstalledPgPassword = "postgres"
            }
            "choco" {
                choco install postgresql17 --params '/Password:postgres' -y --no-progress
                $script:LyNextInstalledPgPassword = "postgres"
            }
            "scoop" {
                scoop install postgresql
                $script:LyNextInstalledPgPassword = "postgres"
            }
        }
    } catch {
        Write-Warn "PostgreSQL install warning (may already installed): $($_.Exception.Message)"
    } finally {
        $ErrorActionPreference = $prevEap
    }
    Refresh-PathEnv
}

function Start-LyNextServices {
    param([string[]]$Components)
    if ($Components -contains "redis") {
        $svc = Get-Service -Name "Redis" -ErrorAction SilentlyContinue
        if ($svc) {
            if ($svc.Status -ne "Running") { Start-Service "Redis" }
            Set-Service "Redis" -StartupType Automatic
            Write-Ok "Redis running"
        }
    }
    if ($Components -contains "postgresql") {
        $hit = Resolve-PgCommonPsqlExe
        $port = if ($hit) { Read-PgCommonPostgresPort -PgRoot $hit.Root } else { 5432 }
        [void](Start-PgCommonWindowsPostgresServices -RestartIfPortClosed -Port $port)
        foreach ($name in Get-PgCommonWindowsPostgresServices) {
            Set-Service -Name $name -StartupType Automatic -ErrorAction SilentlyContinue
            Write-Ok "$name configured"
        }
    }
}

function Invoke-LyNextConfigureLocal {
    Write-Info "Writing config + database/pgvector (data/ly_next/config.yaml)..."
    $candidates = @()
    if ($script:LyNextInstalledPgPassword) { $candidates += $script:LyNextInstalledPgPassword }
    Invoke-PgCommonConfigureLyNextLocal -RepoRoot $RepoRoot `
        -PgPasswordCandidates $candidates -AllowPasswordPrompt -SetupPgvector
}

function Invoke-LyNextFinalizePostgres {
    $st = Get-LyNextInstallStatus
    if (-not $st.PostgreSQL.Installed) { return }
    Write-Info "PostgreSQL: start service, configure, pgvector..."
    Start-LyNextServices -Components @("postgresql")
    Invoke-LyNextConfigureLocal
}

function Invoke-LyNextInstall {
    param([string[]]$Components, [object]$Status, [switch]$ForceInstall)
    $need = @()
    foreach ($c in $Components) {
        if ($ForceInstall -or -not (Test-LyNextComponentSatisfied $c $Status)) { $need += $c }
        else { Write-Info "Skip $c (ready)" }
    }
    if ($need.Count -eq 0) {
        Write-Ok "All selected components are ready."
        if ($Components -contains "postgresql" -or $Components -contains "pgvector") {
            Invoke-LyNextFinalizePostgres
        }
        return
    }

    $pkg = $need | Where-Object { $_ -in @("redis", "postgresql") }
    if ($pkg.Count -gt 0) {
        $mgr = Ensure-PackageManager
        Write-Ok "Package manager: $mgr"
        if ($need -contains "redis") { Install-LyNextRedis $mgr }
        if ($need -contains "postgresql") { Install-LyNextPostgreSQL $mgr }
        Refresh-PathEnv
    }

    Start-LyNextServices -Components $need

    $configure = ($need -contains "redis") -or ($need -contains "postgresql") -or ($need -contains "pgvector")
    if ($configure) {
        if ($need -contains "postgresql" -or $need -contains "pgvector") {
            Invoke-LyNextFinalizePostgres
        } else {
            Invoke-LyNextConfigureLocal
        }
    }
}

function Show-LyNextMainMenu {
    param([object]$Status)
    $missing = Get-LyNextMissingComponents -Status $Status
    Write-Host "Choose:" -ForegroundColor Cyan
    if ($missing.Count -gt 0) {
        Write-Host ("  1) Install all missing (recommended): " + ($missing -join ', ')) -ForegroundColor Green
    } else {
        Write-Host "  1) Nothing to install" -ForegroundColor DarkGray
    }
    Write-Host "  2) Pick components"
    Write-Host "  3) Detect only"
    Write-Host "  0) Exit"
    $c = Read-Host "Option [1]"
    if ([string]::IsNullOrWhiteSpace($c)) { $c = "1" }
    switch ($c.Trim()) {
        "1" { if ($missing.Count -eq 0) { return @() }; return $missing }
        "2" { return Show-LyNextCustomMenu -Status $Status }
        "3" { return $null }
        "0" { return @("__exit__") }
        default { return $(if ($missing.Count -gt 0) { $missing } else { @() }) }
    }
}

function Show-LyNextCustomMenu {
    param([object]$Status)
    Write-Host ""
    Write-Host "Components (skip if already ok):" -ForegroundColor Cyan
    $items = @(
        @{ N = 1; Key = "redis"; Label = "Redis"; Ok = $Status.Redis.Reachable },
        @{ N = 2; Key = "postgresql"; Label = "PostgreSQL"; Ok = $Status.PostgreSQL.Installed },
        @{ N = 3; Key = "pgvector"; Label = "pgvector"; Ok = $Status.Pgvector.Reachable }
    )
    foreach ($it in $items) {
        $st = if ($it.Ok) { "[ok]" } else { "[missing]" }
        Write-Host ("  {0}) {1,-12} {2}" -f $it.N, $it.Label, $st)
    }
    $choice = Read-Host "Numbers, comma-separated (Enter=cancel)"
    if ([string]::IsNullOrWhiteSpace($choice)) { return @("__exit__") }
    $selected = @()
    foreach ($part in ($choice -split '[,\s]+')) {
        switch ($part.Trim()) {
            "1" { $selected += "redis" }
            "2" { $selected += "postgresql" }
            "3" { $selected += "pgvector" }
        }
    }
    return @($selected | Select-Object -Unique)
}

$os = Get-CimInstance Win32_OperatingSystem
Write-Host ""
Write-Host "LY-NEXT install wizard" -ForegroundColor White
Write-Info "OS: $($os.Caption)"

$status = Get-LyNextInstallStatus
Show-LyNextInstallStatus -Status $status

if ($DetectOnly) {
    Write-Ok "Detect done."
    exit 0
}

if ($ConfigureOnly) {
    Assert-LyNextAdmin "启动 Redis/PostgreSQL 服务并写配置"
    Start-LyNextServices -Components @("redis", "postgresql")
    Invoke-LyNextConfigureLocal
    Show-LyNextInstallStatus -Status (Get-LyNextInstallStatus)
    Write-Ok "Configure done. Run: uv run ly"
    exit 0
}

$components = $null
if ($All) {
    $components = @("redis", "postgresql", "pgvector")
} elseif ($Redis -or $PostgreSQL -or $Pgvector) {
    $components = @()
    if ($Redis) { $components += "redis" }
    if ($PostgreSQL) { $components += "postgresql" }
    if ($Pgvector) { $components += "pgvector" }
} elseif ($Yes) {
    $components = Get-LyNextMissingComponents -Status $status
} else {
    $components = Show-LyNextMainMenu -Status $status
}

if ($null -eq $components -or $components -contains "__exit__" -or $components.Count -eq 0) {
    Write-Ok "Exit."
    exit 0
}

Assert-LyNextAdmin "安装依赖并启动服务"
Invoke-LyNextInstall -Components $components -Status $status -ForceInstall:$Force
Show-LyNextInstallStatus -Status (Get-LyNextInstallStatus)
Write-Ok "Done. Start app: uv run ly"
