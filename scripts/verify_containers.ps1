# Build both images and prove they serve, in one command.
#
#     powershell -ExecutionPolicy Bypass -File scripts\verify_containers.ps1
#
# This exists because the runbook had to say the images had never been built:
# Docker was not installed on the machine this was written on. Run this once
# Docker Desktop is up and the caveat in docs/runbook.md section 4 can be deleted.
#
# It builds each image from the repository root, starts it on a spare port, waits
# for the health endpoint, checks the pages and the shared assets, then stops and
# removes the container. It leaves the images behind so a demo can use them.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$apps = @(
    @{ Key = 'pr1'; Image = 'supplyguard';        Port = 7860; Name = 'SupplyGuard (PR1)'
       Paths = @('/api/health', '/api/kpis', '/api/monitoring', '/', '/pages/allocate.html', '/shared/tokens.css') },
    @{ Key = 'p2';  Image = 'trendwear-planner';  Port = 7861; Name = 'TrendWear Planner (P2)'
       Paths = @('/api/health', '/api/kpis', '/api/monitoring', '/', '/pages/reconcile.html', '/shared/table.js') }
)

function Step($m) { Write-Host "`n=== $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  ok    $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  FAIL  $m" -ForegroundColor Red }

# ---------------------------------------------------------------- prerequisites

Step 'Prerequisites'

# The most common failure is not a missing install: it is a shell started before
# the install, or a machine that has not restarted since WSL was enabled.
$rebootPending =
    (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') -or
    (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired')

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $installed = Test-Path (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
    if ($installed -and $rebootPending) {
        Bad 'Docker is installed, but Windows has not restarted since WSL was enabled.'
        Write-Host '        Restart, start Docker Desktop, then run this again.'
    } elseif ($installed) {
        Bad 'Docker is installed but not on this shell PATH. Open a new terminal and run this again.'
    } else {
        Bad 'docker is not on PATH and Docker Desktop is not installed.'
        Write-Host '        winget install --id Docker.DockerDesktop --exact'
    }
    exit 1
}
Ok (docker --version)

if ($rebootPending) {
    Bad 'a restart is pending, so the WSL components are staged but not active yet.'
    Write-Host '        Restart, start Docker Desktop, then run this again.'
    exit 1
}

docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Bad 'the Docker engine is not running. Start Docker Desktop and wait for the whale to settle.'
    exit 1
}
Ok "engine running ($(docker info --format '{{.ServerVersion}}'))"

# The images copy the demo pack in, so it has to exist before they are built.
$python = if (Test-Path '.venv\Scripts\python.exe') { '.venv\Scripts\python.exe' } else { 'python' }
& $python scripts\build_demo_pack.py --check
if ($LASTEXITCODE -ne 0) {
    Bad 'the demo pack is incomplete. Run: python scripts\build_demo_pack.py'
    exit 1
}
Ok 'demo pack present and loadable'

$failures = 0

foreach ($app in $apps) {
    $image     = $app.Image
    $container = "$image-verify"

    # ------------------------------------------------------------------- build

    Step "$($app.Name) - build"
    docker rm -f $container 2>$null | Out-Null
    docker build -f "apps/$($app.Key)/Dockerfile" -t $image .
    if ($LASTEXITCODE -ne 0) { Bad "build failed for $image"; $failures++; continue }

    $size = docker image inspect $image --format '{{.Size}}'
    Ok ("built {0} ({1:N0} MB)" -f $image, ([long]$size / 1MB))

    # --------------------------------------------------------------------- run

    Step "$($app.Name) - run on port $($app.Port)"
    docker run -d --rm --name $container -p "$($app.Port):7860" $image | Out-Null
    if ($LASTEXITCODE -ne 0) { Bad "could not start $container"; $failures++; continue }

    try {
        # Startup loads the parquet tables and warms the headline figures, which
        # takes ten to fifteen seconds. Poll rather than guess.
        $base    = "http://127.0.0.1:$($app.Port)"
        $healthy = $false
        foreach ($attempt in 1..45) {
            Start-Sleep -Seconds 2
            try {
                $r = Invoke-WebRequest "$base/api/health" -UseBasicParsing -TimeoutSec 5
                if ($r.StatusCode -eq 200) { $healthy = $true; break }
            } catch { }
        }

        if (-not $healthy) {
            Bad "$image never became healthy. Last 40 log lines:"
            docker logs --tail 40 $container
            $failures++
            continue
        }
        Ok "healthy after about $($attempt * 2)s"

        foreach ($path in $app.Paths) {
            try {
                $r = Invoke-WebRequest "$base$path" -UseBasicParsing -TimeoutSec 30
                $ms = $r.Headers['X-Response-Time-Ms']
                if ($r.StatusCode -eq 200) {
                    Ok ("{0,-26} 200{1}" -f $path, $(if ($ms) { "  ${ms} ms" } else { '' }))
                } else {
                    Bad ("{0,-26} {1}" -f $path, $r.StatusCode); $failures++
                }
            } catch {
                Bad ("{0,-26} {1}" -f $path, $_.Exception.Message); $failures++
            }
        }

        # Nothing may be trained at request time, and a container that downloads
        # anything at startup would fail on a conference network.
        $logs = docker logs $container 2>&1 | Out-String
        if ($logs -match 'Downloading|kaggle|training') {
            Bad 'the container log mentions downloading or training at startup'
            $failures++
        } else {
            Ok 'no download and no training in the startup log'
        }
    }
    finally {
        docker stop $container 2>$null | Out-Null
    }
}

# --------------------------------------------------------------------- verdict

Step 'Verdict'
if ($failures -eq 0) {
    Write-Host '  Both images build, start and serve every checked path.' -ForegroundColor Green
    Write-Host '  docs/runbook.md section 4 can drop its "not verified in Docker" paragraph.'
    exit 0
}
Write-Host "  $failures check(s) failed. The paragraph in docs/runbook.md section 4 stands." -ForegroundColor Red
exit 1
