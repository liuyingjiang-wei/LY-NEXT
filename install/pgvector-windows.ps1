<# Windows: install/enable pgvector for PostgreSQL. #>

[CmdletBinding()]
param(
    [string]$PgRoot = "",
    [string]$PostgresRootHint = "",
    [ValidateRange(0, 99)]
    [int]$PostgresMajor = 0,
    [string]$Database = "ly_next",
    [string]$Username = "postgres",
    [Alias("Host")]
    [string]$DbHost = "127.0.0.1",
    [int]$Port = 5432,
    [string]$Password = "",
    [string]$VcVarsPath = "",
    [switch]$UseWeiConfig,
    [string]$PgVectorTag = "v0.8.0",
    [switch]$VerifyOnly,
    [switch]$Build,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptRoot = $PSScriptRoot

function Step([string]$msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Find-PsqlExe {
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

            $major = $null
            [void][int]::TryParse($inst.Name, [ref]$major)
            [void]$hits.Add([PSCustomObject]@{
                    Major = ($(if ($major) { $major } else { 0 }))
                    Path  = $candidate
                })
        }
    }

    if ($hits.Count -eq 0) {
        foreach ($segment in (($env:Path -split ';') | Where-Object { $_ })) {
            $candidate = Join-Path $segment.Trim('"') "psql.exe"
            if (Test-Path $candidate) {
                [void]$hits.Add([PSCustomObject]@{ Major = 0; Path = $candidate })
            }
        }
    }

    if ($hits.Count -eq 0) {
        return $null
    }

    if ($PostgresMajor -gt 0) {
        $chosen = @( $hits | Where-Object { $_.Major -eq $PostgresMajor } )
        if ($chosen.Count -eq 0) {
            $majors = @( $hits | ForEach-Object { $_.Major } | Sort-Object -Unique )
            Write-Error ("PostgreSQL major {0} not found. Detected majors: {1}" -f $PostgresMajor, ($majors -join ', '))
        }
        return ($chosen | Sort-Object Path | Select-Object -First 1).Path
    }

    return @( $hits | Sort-Object Major -Descending )[0].Path
}

function Resolve-PgRoot([string]$Explicit, [string]$PsqlPath) {
    if ($Explicit -and (Test-Path $Explicit)) {
        return (Resolve-Path $Explicit).Path
    }
    if ($PsqlPath) {
        $bin = Split-Path $PsqlPath -Parent
        $root = Join-Path $bin ".."
        return (Resolve-Path $root).Path
    }
    return $null
}

function Find-VcVars64 {
    if ($VcVarsPath -and (Test-Path $VcVarsPath)) {
        return (Resolve-Path $VcVarsPath).Path
    }
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

function Read-WeiDb([string]$RepoRoot) {
    $weiRoot = Resolve-Path $RepoRoot
    $yamlPath = Join-Path $weiRoot "data\ly_next\config.yaml"
    if (-not (Test-Path $yamlPath)) { return $null }

    Push-Location $weiRoot.Path
    try {
        $tmp = Join-Path $env:TEMP ("wei_db_export_" + [Guid]::NewGuid().ToString("N") + ".py")
        $nl = [Environment]::NewLine
        $pyLines = @(
            "import json, pathlib",
            "import yaml",
            "",
            "p = pathlib.Path('data/ly_next/config.yaml')",
            "if not p.exists():",
            "    print('{}')",
            "else:",
            "    c = yaml.safe_load(p.read_text(encoding='utf-8')) or {}",
            "    db = c.get('database') or {}",
            "    print(json.dumps({",
            "        'host': db.get('host'),",
            "        'port': db.get('port'),",
            "        'username': db.get('username'),",
            "        'password': db.get('password'),",
            "        'database': db.get('database'),",
            "    }))",
            ""
        )
        $py = [string]::Join($nl, $pyLines)
        Set-Content -Path $tmp -Encoding UTF8 -Value $py
        try { $json = & uv run python $tmp 2>$null } finally { Remove-Item -Force -ErrorAction SilentlyContinue $tmp }
        if (-not $json) { return $null }
        return ($json | ConvertFrom-Json)
    } finally {
        Pop-Location
    }
}

Step "Locate psql / PostgreSQL install root"

if ($UseWeiConfig) {
    $weiProj = Resolve-Path (Join-Path $ScriptRoot "..")
    $wc = Read-WeiDb -RepoRoot $weiProj.Path
    if ($wc) {
        if ($wc.host) { $DbHost = [string]$wc.host }
        if ($wc.port) { $Port = [int]$wc.port }
        if ($wc.username) { $Username = [string]$wc.username }
        if ($wc.database) { $Database = [string]$wc.database }
        if ($wc.password) { $Password = [string]$wc.password }
    }
}

$psql = Find-PsqlExe
if (-not $psql) { Write-Error "psql.exe not found." }
Write-Host "psql: $psql"

$resolvedRoot = Resolve-PgRoot -Explicit $PgRoot -PsqlPath $psql
if (-not $resolvedRoot) { Write-Error "Failed to resolve PGROOT." }
Write-Host "PGROOT: $resolvedRoot"

$vectorCtl = Join-Path $resolvedRoot "share\extension\vector.control"
$hasControl = Test-Path $vectorCtl
Write-Host ("vector.control: " + ($(if ($hasControl) { "present" } else { "missing" })) + " -> $vectorCtl")

if (-not $hasControl -and $VerifyOnly) { Write-Error "vector.control missing. Use -Build to install." }
if (-not $hasControl -and -not $Build -and -not $VerifyOnly) { Write-Error "vector.control missing. Use -Build." }

if (-not $hasControl -and $Build) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Error "git not found." }
    $vcvars = Find-VcVars64
    if (-not $vcvars) { Write-Error "vcvars64.bat not found." }

    $work = Join-Path $env:TEMP ("pgvector_build_" + [Guid]::NewGuid().ToString("N"))
    Step "Prepare source under $work"
    if (-not $DryRun) {
        New-Item -ItemType Directory -Path $work -Force | Out-Null
        Push-Location $work
        try { & git clone --depth 1 --branch $PgVectorTag "https://github.com/pgvector/pgvector.git" } finally { Pop-Location }
    } else {
        Write-Host "[DryRun] would git clone pgvector/$PgVectorTag" -ForegroundColor DarkYellow
    }

    $pgRootDos = $resolvedRoot.TrimEnd('\')
    $srcDir = Join-Path $work "pgvector"

    Step "Build + install with nmake"
    $batchLines = @(
        "@echo off"
        "setlocal"
        ('call "{0}" >nul' -f $vcvars)
        ('set PGROOT={0}' -f $pgRootDos)
        ('cd /d "{0}"' -f $srcDir)
        'nmake /F Makefile.win clean'
        'nmake /F Makefile.win'
        'nmake /F Makefile.win install'
    )
    $crlf = [string]::Concat([char]13, [char]10)
    $batch = [string]::Join($crlf, $batchLines)

    if ($DryRun) {
        Write-Host $batch -ForegroundColor DarkYellow
    } else {
        $tmpBat = Join-Path $env:TEMP ("pgvector_nmake_" + [Guid]::NewGuid().ToString("N") + ".cmd")
        Set-Content -Path $tmpBat -Encoding ASCII -Value $batch
        $quotedBat = '"' + $tmpBat + '"'
        $p = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $quotedBat) -Wait -PassThru -NoNewWindow
        if ($p.ExitCode -ne 0) { Write-Error ("nmake install failed exit code $($p.ExitCode).") }
    }

    if (-not $DryRun -and -not (Test-Path $vectorCtl)) { Write-Error "Still missing vector.control at: $vectorCtl" }
    Write-Host "vector.control is installed." -ForegroundColor Green
}

Step "Verify / enable extension in database"
if (-not $env:PGPASSWORD -and $Password) { $env:PGPASSWORD = $Password }

$sqlAvail = @"
SELECT name, default_version, installed_version FROM pg_available_extensions WHERE name = 'vector';
"@
$sqlInstalled = @"
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
"@
$sqlCreate = @"
CREATE EXTENSION IF NOT EXISTS vector;
"@

if ($DryRun) {
    Write-Host $sqlAvail
    Write-Host $sqlInstalled
    if (-not $VerifyOnly) { Write-Host $sqlCreate }
    exit 0
}

& $psql -h $DbHost -p $Port -U $Username -d $Database -v ON_ERROR_STOP=1 -c $sqlAvail
if ($VerifyOnly) {
    & $psql -h $DbHost -p $Port -U $Username -d $Database -v ON_ERROR_STOP=1 -c $sqlInstalled
    exit 0
}
& $psql -h $DbHost -p $Port -U $Username -d $Database -v ON_ERROR_STOP=1 -c $sqlCreate
& $psql -h $DbHost -p $Port -U $Username -d $Database -v ON_ERROR_STOP=1 -c $sqlInstalled
