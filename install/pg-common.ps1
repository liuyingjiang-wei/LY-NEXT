# Shared PostgreSQL helpers for install/install.ps1 (Windows)
if ($PSScriptRoot) {
    $script:PgCommonInstallDir = $PSScriptRoot
}

function Get-PgCommonPsqlMajorFromExe([string]$PsqlPath) {
    $parent = Split-Path (Split-Path $PsqlPath -Parent) -Parent
    $folderMajor = 0
    [void][int]::TryParse((Split-Path $parent -Leaf), [ref]$folderMajor)
    if ($folderMajor -gt 0) { return $folderMajor }
    try {
        $verLine = (& $PsqlPath --version 2>$null | Select-Object -First 1)
        if ($verLine -match '(?:PostgreSQL|psql)\s+(\d+)') { return [int]$Matches[1] }
    } catch { }
    return 0
}

function Find-PgCommonPostgresInstalls {
    param(
        [string]$PostgresRootHint = "",
        [int]$PostgresMajor = 0
    )
    $pf86 = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86)
    $roots = @(
        (Join-Path $env:ProgramFiles "PostgreSQL")
        (Join-Path $pf86 "PostgreSQL")
    )
    $hits = New-Object System.Collections.Generic.List[object]

    foreach ($r in $roots) {
        if (-not (Test-Path $r)) { continue }
        foreach ($inst in Get-ChildItem -Path $r -Directory -ErrorAction SilentlyContinue) {
            if ($PostgresRootHint) {
                $full = $inst.FullName.ToLowerInvariant()
                $hint = $PostgresRootHint.ToLowerInvariant()
                if (-not $full.Contains($hint)) { continue }
            }
            $candidate = Join-Path $inst.FullName "bin\psql.exe"
            if (-not (Test-Path $candidate)) { continue }
            $major = 0
            [void][int]::TryParse($inst.Name, [ref]$major)
            if ($major -le 0) { $major = Get-PgCommonPsqlMajorFromExe $candidate }
            [void]$hits.Add([PSCustomObject]@{
                    Major = $major
                    Path  = $candidate
                    Root  = $inst.FullName
                })
        }
    }

    if ($hits.Count -eq 0) {
        foreach ($segment in (($env:Path -split ';') | Where-Object { $_ })) {
            $candidate = Join-Path $segment.Trim('"') "psql.exe"
            if (Test-Path $candidate) {
                [void]$hits.Add([PSCustomObject]@{
                        Major = (Get-PgCommonPsqlMajorFromExe $candidate)
                        Path  = $candidate
                        Root  = (Resolve-Path (Join-Path $segment "..")).Path
                    })
            }
        }
    }

    $sorted = @($hits | Sort-Object Major -Descending)
    if ($PostgresMajor -gt 0) {
        $match = @($sorted | Where-Object { $_.Major -eq $PostgresMajor })
        if ($match.Count -gt 0) { return $match }
        if ($sorted.Count -gt 0) {
            Write-Warning (
                "PostgreSQL $PostgresMajor not found; using major $($sorted[0].Major). " +
                "Omit -PostgresMajor to auto-select."
            )
        }
    }
    return $sorted
}

function Resolve-PgCommonPsqlExe {
    param(
        [string]$PostgresRootHint = "",
        [int]$PostgresMajor = 0
    )
    $hits = @(Find-PgCommonPostgresInstalls -PostgresRootHint $PostgresRootHint -PostgresMajor $PostgresMajor)
    if ($hits.Count -eq 0) { return $null }
    $majors = @($hits | ForEach-Object { $_.Major } | Where-Object { $_ -gt 0 } | Sort-Object -Unique)
    if ($majors.Count -gt 0) {
        Write-Host ("Detected PostgreSQL major version(s): " + ($majors -join ', ')) -ForegroundColor DarkGray
    }
    return $hits[0]
}

function Read-PgCommonPostgresPort {
    param(
        [Parameter(Mandatory)][string]$PgRoot,
        [int]$DefaultPort = 5432
    )
    $confPaths = @(
        (Join-Path $PgRoot "data\postgresql.conf")
        (Join-Path $PgRoot "postgresql.conf")
    )
    foreach ($conf in $confPaths) {
        if (-not (Test-Path $conf)) { continue }
        foreach ($line in Get-Content -Path $conf -ErrorAction SilentlyContinue) {
            $t = $line.Trim()
            if ($t -match '^\s*#') { continue }
            if ($t -match '^\s*port\s*=\s*(\d+)') { return [int]$Matches[1] }
        }
    }
    return $DefaultPort
}

function Get-PgCommonWindowsPostgresServices {
    try {
        $r = & powershell -NoProfile -Command `
            "Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name" 2>$null
        return @($r | Where-Object { $_ })
    } catch {
        return @()
    }
}

function Test-PgCommonTcpPort {
    param(
        [string]$HostName = "127.0.0.1",
        [int]$Port = 5432,
        [int]$TimeoutMs = 2000
    )
    $client = $null
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($iar)
        return $true
    } catch {
        return $false
    } finally {
        if ($client) { $client.Dispose() }
    }
}

function Test-PgCommonWindowsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Start-PgCommonWindowsPostgresServices {
    param([switch]$RestartIfPortClosed, [int]$Port = 5432)
    $names = Get-PgCommonWindowsPostgresServices
    if ($names.Count -eq 0) { return $false }

    $needAction = $false
    foreach ($name in $names) {
        $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
        if (-not $svc) { continue }
        $portOpen = (Test-PgCommonTcpPort -HostName "127.0.0.1" -Port $Port)
        if ($svc.Status -ne "Running" -or ($RestartIfPortClosed -and -not $portOpen)) {
            $needAction = $true
            break
        }
    }
    if (-not $needAction) { return $true }

    if (-not (Test-PgCommonWindowsAdmin)) {
        Write-Warning "需要管理员权限才能启动 PostgreSQL 服务。请以管理员 PowerShell 运行 install.ps1，或在「服务」中手动启动 postgresql-x64-*。"
        return $false
    }

    $started = $false
    foreach ($name in $names) {
        $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
        if (-not $svc) { continue }
        $portOpen = (Test-PgCommonTcpPort -HostName "127.0.0.1" -Port $Port)
        if ($svc.Status -eq "Running" -and $RestartIfPortClosed -and -not $portOpen) {
            Write-Host "Restarting $name (service running but port $Port closed)..." -ForegroundColor Yellow
            Restart-Service -Name $name -Force -ErrorAction SilentlyContinue
            $started = $true
        } elseif ($svc.Status -ne "Running") {
            Write-Host "Starting PostgreSQL service: $name" -ForegroundColor Cyan
            Start-Service -Name $name -ErrorAction Stop
            $started = $true
        }
    }
    return $started
}

function Wait-PgCommonTcpPort {
    param(
        [string]$HostName = "127.0.0.1",
        [int]$Port = 5432,
        [int]$TimeoutSeconds = 45
    )
    for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
        if (Test-PgCommonTcpPort -HostName $HostName -Port $Port) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Ensure-PgCommonPostgresReady {
    param(
        [Parameter(Mandatory)][string]$Psql,
        [Parameter(Mandatory)][string]$PgRoot,
        [string]$DbHost = "127.0.0.1",
        [int]$Port = 0,
        [string]$Username = "postgres",
        [string]$Password = "",
        [string]$ProbeDatabase = "postgres"
    )
    if ($Port -le 0) {
        $Port = Read-PgCommonPostgresPort -PgRoot $PgRoot -DefaultPort 5432
    }
    Write-Host "PostgreSQL port (from config / postgresql.conf): $Port" -ForegroundColor DarkGray

    $tryHosts = @("127.0.0.1")
    if ($DbHost -and $DbHost -notin $tryHosts) { $tryHosts += $DbHost }
    if ($DbHost -eq "localhost") { $tryHosts = @("127.0.0.1", "localhost") }

    foreach ($h in $tryHosts) {
        if (Test-PgCommonTcpPort -HostName $h -Port $Port) {
            $ok = Invoke-PgCommonPsql -Psql $Psql -DbHost $h -Port $Port -Username $Username `
                -Password $Password -Database $ProbeDatabase -Sql "SELECT 1" -Quiet
            if ($ok) { return @{ Host = $h; Port = $Port } }
        }
    }

    Write-Host "PostgreSQL not accepting connections on port $Port; starting Windows service..." -ForegroundColor Yellow
    [void](Start-PgCommonWindowsPostgresServices -RestartIfPortClosed -Port $Port)

    if (-not (Wait-PgCommonTcpPort -HostName "127.0.0.1" -Port $Port)) {
        throw (
            "PostgreSQL still not listening on 127.0.0.1:${Port}. " +
            "Check postgresql.conf (listen_addresses, port) and Windows service postgresql-x64-*."
        )
    }

    foreach ($h in $tryHosts) {
        $ok = Invoke-PgCommonPsql -Psql $Psql -DbHost $h -Port $Port -Username $Username `
            -Password $Password -Database $ProbeDatabase -Sql "SELECT 1" -Quiet
        if ($ok) { return @{ Host = $h; Port = $Port } }
    }

    throw (
        "Port $Port is open but psql auth failed. Set database.password in data/ly_next/config.yaml " +
        "(postgres user password from installation)."
    )
}

function Invoke-PgCommonPsql {
    param(
        [Parameter(Mandatory)][string]$Psql,
        [string]$DbHost = "127.0.0.1",
        [int]$Port = 5432,
        [string]$Username = "postgres",
        [string]$Password = "",
        [string]$Database = "postgres",
        [Parameter(Mandatory)][string]$Sql,
        [switch]$Quiet
    )
    $prev = $env:PGPASSWORD
    $env:PGPASSWORD = $Password
    try {
        $out = & $Psql -w -h $DbHost -p $Port -U $Username -d $Database -v ON_ERROR_STOP=1 -c $Sql 2>&1
        if ($LASTEXITCODE -ne 0) {
            if (-not $Quiet) { Write-Host $out }
            return $false
        }
        if (-not $Quiet) { Write-Host $out }
        return $true
    } catch {
        if (-not $Quiet) { Write-Host $_ }
        return $false
    } finally {
        if ($null -ne $prev) { $env:PGPASSWORD = $prev } else { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
    }
}

function Test-PgCommonPgvectorInDatabase {
    param(
        [string]$Psql,
        [string]$DbHost,
        [int]$Port,
        [string]$Username,
        [string]$Password,
        [string]$Database = "ly_next"
    )
    $sql = "SELECT 1 FROM pg_extension WHERE extname='vector';"
    $prev = $env:PGPASSWORD
    $env:PGPASSWORD = $Password
    try {
        $r = & $Psql -w -h $DbHost -p $Port -U $Username -d $Database -tAc $sql 2>$null
        return ($r -match "1")
    } catch {
        return $false
    } finally {
        if ($null -ne $prev) { $env:PGPASSWORD = $prev } else { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
    }
}

function Get-PgCommonVectorControlPath {
    param([string]$PgRoot)
    if (-not $PgRoot) { return $null }
    $p = Join-Path $PgRoot "share\extension\vector.control"
    if (Test-Path $p) { return $p }
    return $null
}

function Read-PgCommonLyNextDatabaseConfig {
    param([string]$RepoRoot)
    $root = Resolve-Path $RepoRoot
    $yamlPath = Join-Path $root "data\ly_next\config.yaml"
    $defaults = @{
        host     = "127.0.0.1"
        port     = 5432
        username = "postgres"
        password = ""
        database = "ly_next"
    }
    if (-not (Test-Path $yamlPath)) { return $defaults }

    Push-Location $root.Path
    try {
        $tmp = Join-Path $env:TEMP ("ly_db_cfg_" + [Guid]::NewGuid().ToString("N") + ".py")
        $py = @"
import json, pathlib, yaml
p = pathlib.Path('data/ly_next/config.yaml')
c = yaml.safe_load(p.read_text(encoding='utf-8')) or {} if p.exists() else {}
db = c.get('database') or {}
print(json.dumps({
    'host': db.get('host') or '127.0.0.1',
    'port': int(db.get('port') or 5432),
    'username': db.get('username') or 'postgres',
    'password': '' if db.get('password') is None else str(db.get('password')),
    'database': db.get('database') or 'ly_next',
}))
"@
        Set-Content -Path $tmp -Encoding UTF8 -Value $py
        try {
            $json = & uv run python $tmp 2>$null
            if (-not $json) { $json = & python $tmp 2>$null }
            if (-not $json) { $json = & py -3 $tmp 2>$null }
            if ($json) {
                $o = $json | ConvertFrom-Json
                return @{
                    host     = [string]$o.host
                    port     = [int]$o.port
                    username = [string]$o.username
                    password = [string]$o.password
                    database = [string]$o.database
                }
            }
        } finally {
            Remove-Item -Force -ErrorAction SilentlyContinue $tmp
        }
    } finally {
        Pop-Location
    }
    return $defaults
}

function Find-PgCommonVcVars64 {
    param([string]$VcVarsPath = "")
    if ($VcVarsPath -and (Test-Path $VcVarsPath)) { return (Resolve-Path $VcVarsPath).Path }
    $pf86 = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86)
    foreach ($p in @(
            (Join-Path $env:ProgramFiles "Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat")
            (Join-Path $env:ProgramFiles "Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat")
            (Join-Path $env:ProgramFiles "Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat")
            (Join-Path $pf86 "Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat")
            (Join-Path $pf86 "Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat")
        )) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Ensure-PgCommonLyNextDatabase {
    param(
        [Parameter(Mandatory)][string]$Psql,
        [string]$DbHost,
        [int]$Port,
        [string]$Username,
        [string]$Password,
        [string]$Database = "ly_next"
    )
    $check = "SELECT 1 FROM pg_database WHERE datname = '$($Database.Replace("'", "''"))';"
    $prev = $env:PGPASSWORD
    $env:PGPASSWORD = $Password
    try {
        $exists = & $Psql -w -h $DbHost -p $Port -U $Username -d postgres -tAc $check 2>$null
        if ($exists -match "1") { return $true }
        $create = "CREATE DATABASE $($Database.Replace('"', '""'));"
        & $Psql -w -h $DbHost -p $Port -U $Username -d postgres -v ON_ERROR_STOP=1 -c $create 2>&1 | Out-Host
        return ($LASTEXITCODE -eq 0)
    } finally {
        if ($null -ne $prev) { $env:PGPASSWORD = $prev } else { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
    }
}

function Get-PgCommonDefaultGithubProxies {
    $list = [System.Collections.Generic.List[string]]::new()
    $preferred = [string]$env:LY_NEXT_GITHUB_PROXY
    if (-not [string]::IsNullOrWhiteSpace($preferred)) {
        $norm = $preferred.Trim().TrimEnd("/") + "/"
        [void]$list.Add($norm)
    }
    foreach ($p in @(
            "https://gh-proxy.com/"
            "https://ghfast.top/"
            "https://ghproxy.net/"
            "https://gh.ddlc.top/"
            "https://mirror.ghproxy.com/"
            "https://hub.gitmirror.com/"
            "https://cf.ghproxy.cc/"
            "https://ghp.ci/"
        )) {
        if (-not $list.Contains($p)) { [void]$list.Add($p) }
    }
    return @($list)
}

function New-PgCommonProxiedGithubUrl {
    param(
        [Parameter(Mandatory)][string]$Proxy,
        [Parameter(Mandatory)][string]$UpstreamUrl
    )
    return "{0}/{1}" -f $Proxy.TrimEnd("/"), $UpstreamUrl.Trim()
}

function Select-PgCommonGithubProxies {
    param(
        [string]$ProbeUrl = "https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.0.zip",
        [int]$TimeoutSec = 15
    )
    if ($env:LY_NEXT_GITHUB_PROXY_SKIP_PROBE -eq "1") {
        return Get-PgCommonDefaultGithubProxies
    }

    Write-Host "正在测速 GitHub 代理 (${TimeoutSec}s 超时)..." -ForegroundColor DarkGray
    $ranked = foreach ($p in (Get-PgCommonDefaultGithubProxies)) {
        $url = New-PgCommonProxiedGithubUrl -Proxy $p -UpstreamUrl $ProbeUrl
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $ok = $false
        $len = 0
        try {
            $resp = Invoke-WebRequest -Uri $url -Method Head -UseBasicParsing -TimeoutSec $TimeoutSec
            $ok = ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400)
            $cl = $resp.Headers["Content-Length"]
            if ($cl) { [void][int]::TryParse([string]$cl, [ref]$len) }
        } catch {
            $ok = $false
        }
        [PSCustomObject]@{ Proxy = $p; OK = $ok; Ms = $sw.ElapsedMilliseconds; Len = $len }
    }

    $good = @($ranked | Where-Object { $_.OK -and $_.Len -gt 50000 } | Sort-Object Ms)
    if ($good.Count -eq 0) {
        $good = @($ranked | Where-Object { $_.OK } | Sort-Object Ms)
    }
    if ($good.Count -gt 0) {
        $summary = ($good | ForEach-Object { "{0}({1}ms)" -f $_.Proxy.TrimEnd("/"), $_.Ms }) -join ", "
        Write-Host "GitHub 代理测速结果: $summary" -ForegroundColor DarkGray
        return @($good | ForEach-Object { $_.Proxy })
    }

    Write-Warning "GitHub 代理测速均失败，将尝试直连 GitHub。"
    return @()
}

function Remove-PgCommonPgvectorWorktree {
    param([Parameter(Mandatory)][string]$Dest)
    if (Test-Path -LiteralPath $Dest) {
        Remove-Item -LiteralPath $Dest -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Expand-PgCommonPgvectorZip {
    param(
        [Parameter(Mandatory)][string]$WorkDir,
        [Parameter(Mandatory)][string]$ZipPath,
        [Parameter(Mandatory)][string]$PgVectorTag
    )
    $dest = Join-Path $WorkDir "pgvector"
    $ver = $PgVectorTag.TrimStart("v")
    Expand-Archive -Path $ZipPath -DestinationPath $WorkDir -Force
    Remove-Item -Force -ErrorAction SilentlyContinue $ZipPath

    $extracted = Join-Path $WorkDir "pgvector-$ver"
    if (-not (Test-Path -LiteralPath (Join-Path $extracted "Makefile.win"))) {
        $alt = Get-ChildItem -Path $WorkDir -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "pgvector-*" } |
            Select-Object -First 1
        if ($alt) { $extracted = $alt.FullName }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $extracted "Makefile.win"))) {
        throw "解压后的 pgvector 目录无效: $extracted"
    }
    Remove-PgCommonPgvectorWorktree -Dest $dest
    Rename-Item -LiteralPath $extracted -NewName "pgvector"
    return (Resolve-Path -LiteralPath $dest).Path
}

function Get-PgCommonPgvectorSource {
    param(
        [Parameter(Mandatory)][string]$WorkDir,
        [string]$PgVectorTag = "v0.8.0"
    )
    $dest = Join-Path $WorkDir "pgvector"
    if (Test-Path -LiteralPath (Join-Path $dest "Makefile.win")) {
        return (Resolve-Path -LiteralPath $dest).Path
    }

    New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
    $repoUrl = "https://github.com/pgvector/pgvector.git"
    $zipUrl = "https://github.com/pgvector/pgvector/archive/refs/tags/$PgVectorTag.zip"
    $proxies = Select-PgCommonGithubProxies -ProbeUrl $zipUrl

    $cloneUrls = [System.Collections.Generic.List[string]]::new()
    foreach ($p in $proxies) {
        [void]$cloneUrls.Add((New-PgCommonProxiedGithubUrl -Proxy $p -UpstreamUrl $repoUrl))
    }
    if (-not $cloneUrls.Contains($repoUrl)) { [void]$cloneUrls.Add($repoUrl) }

    if (Get-Command git -ErrorAction SilentlyContinue) {
        foreach ($cloneUrl in $cloneUrls) {
            Remove-PgCommonPgvectorWorktree -Dest $dest
            Write-Host "git clone: $cloneUrl" -ForegroundColor DarkGray
            Push-Location $WorkDir
            try {
                & git clone --depth 1 --branch $PgVectorTag $cloneUrl pgvector 2>&1 | Out-Host
            } catch {
                Write-Warning "git clone 失败: $cloneUrl"
            } finally {
                Pop-Location
            }
            if (Test-Path -LiteralPath (Join-Path $dest "Makefile.win")) {
                return (Resolve-Path -LiteralPath $dest).Path
            }
        }
    }

    Write-Warning "git clone pgvector 失败，尝试通过代理下载源码 zip..."
    $zipUrls = [System.Collections.Generic.List[string]]::new()
    foreach ($p in $proxies) {
        [void]$zipUrls.Add((New-PgCommonProxiedGithubUrl -Proxy $p -UpstreamUrl $zipUrl))
    }
    if (-not $zipUrls.Contains($zipUrl)) { [void]$zipUrls.Add($zipUrl) }

    $minZipBytes = 100000
    foreach ($url in $zipUrls) {
        $zipPath = Join-Path $WorkDir "pgvector-$PgVectorTag.zip"
        Remove-Item -Force -ErrorAction SilentlyContinue $zipPath
        Write-Host "下载 zip: $url" -ForegroundColor DarkGray
        try {
            Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing -TimeoutSec 180
            if ((Get-Item -LiteralPath $zipPath).Length -lt $minZipBytes) {
                Write-Warning "zip 体积异常，跳过: $url"
                continue
            }
            return Expand-PgCommonPgvectorZip -WorkDir $WorkDir -ZipPath $zipPath -PgVectorTag $PgVectorTag
        } catch {
            Write-Warning "zip 下载失败: $url"
        }
    }

    throw (
        "无法获取 pgvector 源码（git 与 zip 均失败）。可设置环境变量后重试:`n" +
        "  `$env:LY_NEXT_GITHUB_PROXY = 'https://gh-proxy.com/'`n" +
        "或手动下载: $zipUrl`n" +
        "解压到 data/ly_next/cache/pgvector_src/pgvector，再运行 .\install.ps1 -Pgvector"
    )
}

function Invoke-PgCommonPgvectorSetup {
    param(
        [string]$RepoRoot,
        [switch]$BuildIfMissing,
        [string]$PgVectorTag = "v0.8.0",
        [string]$VcVarsPath = ""
    )
    $cfg = Read-PgCommonLyNextDatabaseConfig -RepoRoot $RepoRoot
    $hit = Resolve-PgCommonPsqlExe
    if (-not $hit) { throw "未找到 psql，请先安装 PostgreSQL。" }

    $psql = $hit.Path
    $pgRoot = $hit.Root
    $port = if ($cfg.port -gt 0) { $cfg.port } else { 0 }
    $ready = Ensure-PgCommonPostgresReady -Psql $psql -PgRoot $pgRoot -DbHost $cfg.host `
        -Port $port -Username $cfg.username -Password $cfg.password -ProbeDatabase "postgres"
    $DbHost = $ready.Host
    $Port = $ready.Port

    if (-not (Ensure-PgCommonLyNextDatabase -Psql $psql -DbHost $DbHost -Port $Port `
            -Username $cfg.username -Password $cfg.password -Database $cfg.database)) {
        throw "无法创建数据库 $($cfg.database)"
    }

    $vectorCtl = Get-PgCommonVectorControlPath -PgRoot $pgRoot
    if ($vectorCtl) {
        Write-Host "pgvector 扩展文件已存在，跳过编译。" -ForegroundColor DarkGray
    }
    if (-not $vectorCtl -and $BuildIfMissing) {
        $vcvars = Find-PgCommonVcVars64 -VcVarsPath $VcVarsPath
        if (-not $vcvars) { throw "未找到 Visual Studio vcvars64.bat，无法编译 pgvector。" }

        $cacheRoot = Join-Path $RepoRoot "data\ly_next\cache"
        $work = Join-Path $cacheRoot "pgvector_src"
        $pgvectorSrc = Get-PgCommonPgvectorSource -WorkDir $work -PgVectorTag $PgVectorTag
        $pgRootQ = $pgRoot.TrimEnd('\')
        $buildLog = Join-Path $env:TEMP ("pgvector_nmake_" + [Guid]::NewGuid().ToString("N") + ".log")
        $batch = @(
            "@echo off"
            "setlocal"
            "call :pgvector_build > `"$buildLog`" 2>&1"
            "exit /b %ERRORLEVEL%"
            ":pgvector_build"
            ('call "{0}" >nul' -f $vcvars)
            ('set "PGROOT={0}"' -f $pgRootQ)
            ('cd /d "{0}"' -f $pgvectorSrc)
            "if errorlevel 1 exit /b 1"
            "nmake /F Makefile.win clean"
            "if errorlevel 1 exit /b 1"
            "nmake /F Makefile.win"
            "if errorlevel 1 exit /b 1"
            "nmake /F Makefile.win install"
            "exit /b %ERRORLEVEL%"
        ) -join "`r`n"
        $tmpBat = Join-Path $env:TEMP ("pgvector_nmake_" + [Guid]::NewGuid().ToString("N") + ".cmd")
        Set-Content -Path $tmpBat -Encoding ASCII -Value $batch
        Write-Host "正在编译安装 pgvector (约 1-3 分钟，请稍候)..." -ForegroundColor Cyan
        Write-Host "源码目录: $pgvectorSrc" -ForegroundColor DarkGray
        $p = Start-Process -FilePath "cmd.exe" `
            -ArgumentList @("/c", $tmpBat) `
            -Wait -PassThru -NoNewWindow
        if (Test-Path -LiteralPath $buildLog) {
            Get-Content -LiteralPath $buildLog -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
        }
        Remove-Item -Force -ErrorAction SilentlyContinue $tmpBat
        if ($p.ExitCode -ne 0) {
            if (Test-Path -LiteralPath $buildLog) {
                Write-Warning "完整编译日志: $buildLog"
            }
            throw "pgvector 编译安装失败 (exit $($p.ExitCode))。"
        }
        Remove-Item -Force -ErrorAction SilentlyContinue $buildLog
        Write-Host "pgvector 编译安装完成。" -ForegroundColor Green
        $vectorCtl = Get-PgCommonVectorControlPath -PgRoot $pgRoot
    }

    if (-not $vectorCtl) {
        throw "缺少 vector.control，需要安装 VS 构建工具后重试，或手动执行 install/pgvector.md"
    }

    if (Test-PgCommonPgvectorInDatabase -Psql $psql -DbHost $DbHost -Port $Port `
            -Username $cfg.username -Password $cfg.password -Database $cfg.database) {
        Write-Host "pgvector 已在库 $($cfg.database) 中启用。" -ForegroundColor Green
        return
    }

    Write-Host "正在启用 pgvector 扩展 (CREATE EXTENSION)..." -ForegroundColor Cyan
    $sqlCreate = "CREATE EXTENSION IF NOT EXISTS vector;"
    if (-not (Invoke-PgCommonPsql -Psql $psql -DbHost $DbHost -Port $Port -Username $cfg.username `
            -Password $cfg.password -Database $cfg.database -Sql $sqlCreate)) {
        throw "CREATE EXTENSION vector 失败，请检查 database.password（data/ly_next/config.yaml）"
    }
    Write-Host "pgvector 已在库 $($cfg.database) 中启用。" -ForegroundColor Green
}

function Invoke-PgCommonRunConfigureLocal {
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [hashtable]$Patch = @{}
    )
    if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
        throw "RepoRoot 不能为空，请在项目根目录运行 .\install.ps1"
    }
    $repoAbs = (Resolve-Path -LiteralPath $RepoRoot).ProviderPath
    $scriptPath = Join-Path $repoAbs "install\configure_local.py"
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        throw "未找到 configure_local.py: $scriptPath"
    }
    if (-not $Patch) { $Patch = @{} }
    $json = $Patch | ConvertTo-Json -Compress -Depth 8
    $tempDir = if ($env:TEMP) { $env:TEMP } else { [System.IO.Path]::GetTempPath() }
    $patchFile = Join-Path $tempDir ("ly_next_cfg_" + [Guid]::NewGuid().ToString("N") + ".json")
    [System.IO.File]::WriteAllText($patchFile, $json, [System.Text.UTF8Encoding]::new($false))
    Push-Location -LiteralPath $repoAbs
    try {
        $pyArgs = @(
            $scriptPath, "--repo-root", $repoAbs, "--patch-file", $patchFile
        )
        $out = & uv run python @pyArgs 2>&1
        if ($LASTEXITCODE -ne 0 -or -not $out) {
            $out = & python @pyArgs 2>&1
        }
        if ($LASTEXITCODE -ne 0 -or -not $out) {
            $out = & py -3 @pyArgs 2>&1
        }
        if ($LASTEXITCODE -ne 0 -or -not $out) {
            throw "无法运行 configure_local.py（请在项目根目录执行 uv sync，或安装 python + pyyaml）: $out"
        }
        return ($out | Select-Object -Last 1).ToString().Trim()
    } finally {
        Pop-Location
        Remove-Item -Force -ErrorAction SilentlyContinue $patchFile
    }
}

function Test-PgCommonPostgresAuth {
    param(
        [Parameter(Mandatory)][string]$Psql,
        [string]$DbHost = "127.0.0.1",
        [int]$Port = 5432,
        [string]$Username = "postgres",
        [string]$Password = ""
    )
    return Invoke-PgCommonPsql -Psql $Psql -DbHost $DbHost -Port $Port -Username $Username `
        -Password $Password -Database "postgres" -Sql "SELECT 1" -Quiet
}

function Find-PgCommonPostgresPassword {
    param(
        [Parameter(Mandatory)][string]$Psql,
        [Parameter(Mandatory)][string]$PgRoot,
        [Parameter(Mandatory)][string]$RepoRoot,
        [string]$DbHost = "127.0.0.1",
        [int]$Port = 0,
        [string]$Username = "postgres",
        [string[]]$ExtraCandidates = @(),
        [switch]$AllowPrompt
    )
    if ($Port -le 0) {
        $Port = Read-PgCommonPostgresPort -PgRoot $PgRoot -DefaultPort 5432
    }

    $existing = (Read-PgCommonLyNextDatabaseConfig -RepoRoot $RepoRoot).password
    $candidates = [System.Collections.Generic.List[string]]::new()
    foreach ($c in @(
            $env:LY_NEXT_POSTGRES_PASSWORD
            $env:POSTGRES_PASSWORD
            $ExtraCandidates
            $existing
        )) {
        if ($null -eq $c) { continue }
        $s = [string]$c
        if ($candidates -notcontains $s) { [void]$candidates.Add($s) }
    }
    foreach ($c in @("postgres")) {
        if ($candidates -notcontains $c) { [void]$candidates.Add($c) }
    }

    foreach ($pw in $candidates) {
        if (Test-PgCommonPostgresAuth -Psql $Psql -DbHost $DbHost -Port $Port -Username $Username -Password $pw) {
            return $pw
        }
    }

    if ($AllowPrompt) {
        Write-Host "无法自动识别 PostgreSQL 密码，请输入安装 postgres 用户时设置的密码:" -ForegroundColor Yellow
        $typed = Read-Host
        if (Test-PgCommonPostgresAuth -Psql $Psql -DbHost $DbHost -Port $Port -Username $Username -Password $typed) {
            return $typed
        }
    }
    return $null
}

function Get-PgCommonRedisReachable {
    param(
        [string]$HostName = "127.0.0.1",
        [int]$Port = 6379,
        [string]$Password = ""
    )
    if (-not (Get-Command redis-cli -ErrorAction SilentlyContinue)) { return $false }
    $args = @("-h", $HostName, "-p", "$Port")
    if ($Password) { $args += @("-a", $Password) }
    $args += "ping"
    try {
        $r = & redis-cli @args 2>$null
        return ($r -match "PONG")
    } catch {
        return $false
    }
}

function Find-PgCommonRedisPassword {
    param(
        [string]$HostName = "127.0.0.1",
        [int]$Port = 6379
    )
    if (Get-PgCommonRedisReachable -HostName $HostName -Port $Port -Password "") { return "" }
    if (-not (Get-Command redis-cli -ErrorAction SilentlyContinue)) { return "" }
    try {
        $rp = & redis-cli -h $HostName -p $Port CONFIG GET requirepass 2>$null
        if ($rp -is [array] -and $rp.Count -ge 2) {
            $pw = [string]$rp[1]
            if ($pw -and $pw -ne "(nil)" -and (Get-PgCommonRedisReachable -HostName $HostName -Port $Port -Password $pw)) {
                return $pw
            }
        }
    } catch { }
    return ""
}

function Invoke-PgCommonConfigureLyNextLocal {
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [string[]]$PgPasswordCandidates = @(),
        [switch]$AllowPasswordPrompt,
        [switch]$SetupPgvector
    )
    if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
        throw "RepoRoot 不能为空，请在项目根目录运行 .\install.ps1"
    }
    $repo = (Resolve-Path -LiteralPath $RepoRoot).ProviderPath
    $dbHost = if ($env:LY_NEXT_DATABASE_HOST) { $env:LY_NEXT_DATABASE_HOST }
        elseif ($env:DATABASE_HOST) { $env:DATABASE_HOST } else { "127.0.0.1" }
    $dbPort = 5432
    if ($env:LY_NEXT_DATABASE_PORT) { $dbPort = [int]$env:LY_NEXT_DATABASE_PORT }
    elseif ($env:DATABASE_PORT) { $dbPort = [int]$env:DATABASE_PORT }
    $redisHost = if ($env:LY_NEXT_REDIS_HOST) { $env:LY_NEXT_REDIS_HOST }
        elseif ($env:REDIS_HOST) { $env:REDIS_HOST } else { "127.0.0.1" }
    $redisPort = 6379
    if ($env:LY_NEXT_REDIS_PORT) { $redisPort = [int]$env:LY_NEXT_REDIS_PORT }
    elseif ($env:REDIS_PORT) { $redisPort = [int]$env:REDIS_PORT }

    $patch = @{
        server = @{
            host = "0.0.0.0"
            port = 8000
        }
        database = @{
            host              = $dbHost
            port              = $dbPort
            username          = "postgres"
            database          = "ly_next"
            try_unix_socket   = $false
        }
        redis = @{
            host = $redisHost
            port = $redisPort
            db   = 0
        }
    }

    $pgAuthOk = $false
    $existingPw = (Read-PgCommonLyNextDatabaseConfig -RepoRoot $repo).password
    $hit = Resolve-PgCommonPsqlExe
    if ($hit) {
        $port = if ($dbPort -gt 0) { $dbPort } elseif ($dbCfg.port -gt 0) { $dbCfg.port } else { (Read-PgCommonPostgresPort -PgRoot $hit.Root -DefaultPort 5432) }
        $patch.database.port = $port
        [void](Start-PgCommonWindowsPostgresServices -RestartIfPortClosed -Port $port)
        if (-not (Wait-PgCommonTcpPort -HostName $dbHost -Port $port -TimeoutSeconds 30)) {
            Write-Warning "PostgreSQL 在 ${dbHost}:$port 未监听；已在 config 中写入连接信息，请启动 postgresql-x64-* 后重新运行 -ConfigureOnly"
            if (-not [string]::IsNullOrEmpty($existingPw)) {
                $patch.database.password = $existingPw
            } else {
                $patch.database.password = ""
            }
        } else {
            $pgPw = Find-PgCommonPostgresPassword -Psql $hit.Path -PgRoot $hit.Root -RepoRoot $repo `
                -Port $port -ExtraCandidates $PgPasswordCandidates -AllowPrompt:$AllowPasswordPrompt
            if ($null -ne $pgPw) {
                $patch.database.password = $pgPw
                $pgAuthOk = $true
            } elseif (-not [string]::IsNullOrEmpty($existingPw)) {
                $patch.database.password = $existingPw
                $pgAuthOk = Test-PgCommonPostgresAuth -Psql $hit.Path -DbHost $dbHost -Port $port `
                    -Username $patch.database.username -Password $existingPw
                if (-not $pgAuthOk) {
                    Write-Warning (
                        "config.yaml 中的 database.password 无法连接 PostgreSQL；" +
                        "请修正 data/ly_next/config.yaml 后重新运行 .\install.ps1 -ConfigureOnly"
                    )
                }
            } else {
                $patch.database.password = ""
                Write-Warning "未能识别 PostgreSQL 密码；请运行 .\install.ps1 -ConfigureOnly 并按提示输入"
            }
        }
    }

    $redisPort = $patch.redis.port
    if (Get-Command redis-cli -ErrorAction SilentlyContinue) {
        $patch.redis.password = Find-PgCommonRedisPassword -HostName $redisHost -Port $redisPort
    } else {
        $patch.redis.password = ""
    }

    $cfgPath = Invoke-PgCommonRunConfigureLocal -RepoRoot $repo -Patch $patch
    Write-Host "已更新配置: $cfgPath" -ForegroundColor Green

    if ($SetupPgvector -and $hit -and $pgAuthOk) {
        try {
            Invoke-PgCommonPgvectorSetup -RepoRoot $repo -BuildIfMissing
        } catch {
            Write-Warning "pgvector: $($_.Exception.Message)"
        }
    }

    return $cfgPath
}
