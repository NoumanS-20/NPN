# Deploy both applications to Google Cloud Run.
#
#     powershell -ExecutionPolicy Bypass -File scripts\deploy_cloudrun.ps1
#     powershell -ExecutionPolicy Bypass -File scripts\deploy_cloudrun.ps1 -App pr1
#     powershell -ExecutionPolicy Bypass -File scripts\deploy_cloudrun.ps1 -Check
#
# Cloud Run builds the image itself with Cloud Build, so nothing here needs a
# local Docker. That matters: Docker has never been installed on the machine
# this was written on.
#
# Prerequisites, all one-off and all yours to do:
#   1. Install the gcloud CLI: https://cloud.google.com/sdk/docs/install
#   2. gcloud auth login              (opens your browser)
#   3. gcloud config set project YOUR_PROJECT_ID
#   4. Enable billing on that project. The free tier covers a demo comfortably;
#      billing simply has to be attached.

param(
    [ValidateSet("pr1", "p2", "both")]
    [string]$App = "both",
    [string]$Region = "asia-south1",
    [switch]$Check
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot

# 2 GiB because the planning context plus three fitted models sits well above
# the 512 MB that free tiers elsewhere offer - that is what ruled them out.
# 2 CPUs because the eight-plant solve is CPU-bound and single-threaded CBC on
# one vCPU roughly doubles it.
$MEMORY = "2Gi"
$CPU = "2"
$TIMEOUT = "300"
$PORT = "7860"

$services = @{
    pr1 = @{ Name = "supplyguard";       Dir = "build\spaces\pr1"; Label = "SupplyGuard (PR1)" }
    p2  = @{ Name = "trendwear-planner"; Dir = "build\spaces\p2";  Label = "TrendWear Planner (P2)" }
}

function Step($m) { Write-Host "`n=== $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  ok    $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  FAIL  $m" -ForegroundColor Red }
function Note($m) { Write-Host "        $m" -ForegroundColor DarkGray }

# ---------------------------------------------------------------- preflight

Step "Prerequisites"

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Bad "gcloud is not installed."
    Note "Install it: https://cloud.google.com/sdk/docs/install"
    Note "Then: gcloud auth login"
    exit 1
}
Ok "gcloud found"

$account = (gcloud config get-value account 2>$null)
if (-not $account -or $account -eq "(unset)") {
    Bad "not logged in."
    Note "Run: gcloud auth login"
    exit 1
}
Ok "authenticated as $account"

$project = (gcloud config get-value project 2>$null)
if (-not $project -or $project -eq "(unset)") {
    Bad "no project selected."
    Note "Run: gcloud config set project YOUR_PROJECT_ID"
    Note "List them with: gcloud projects list"
    exit 1
}
Ok "project $project, region $Region"

if ($Check) {
    Step "Deployed services"
    gcloud run services list --region $Region --format="table(SERVICE,URL,LAST_DEPLOYED_BY)" 2>&1 |
        ForEach-Object { Note $_ }
    exit 0
}

# Cloud Build and Cloud Run have to be switched on once per project. Doing it
# here is cheaper than letting the first deploy fail with an API-disabled error
# that reads like a permissions problem.
Step "Enabling the APIs this needs (no-op after the first run)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com 2>&1 |
    ForEach-Object { Note $_ }
if ($LASTEXITCODE -ne 0) {
    Bad "could not enable the APIs - usually this means billing is not attached to $project."
    Note "https://console.cloud.google.com/billing"
    exit 1
}
Ok "run, cloudbuild and artifactregistry enabled"

# ---------------------------------------------------------------- deploying

$targets = if ($App -eq "both") { @("pr1", "p2") } else { @($App) }
$failed = 0

foreach ($key in $targets) {
    $svc = $services[$key]
    $dir = Join-Path $root $svc.Dir

    Step "$($svc.Label)  ->  $($svc.Name)"

    if (-not (Test-Path (Join-Path $dir "Dockerfile"))) {
        Bad "$dir has no Dockerfile."
        Note "Stage it first: .venv\Scripts\python.exe scripts\stage_space.py $key --force"
        $failed++
        continue
    }

    $count = (Get-ChildItem $dir -Recurse -File).Count
    $mb = [math]::Round((Get-ChildItem $dir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
    Ok "$count files, $mb MB - Cloud Build compiles this in the cloud"

    gcloud run deploy $svc.Name `
        --source $dir `
        --region $Region `
        --platform managed `
        --allow-unauthenticated `
        --memory $MEMORY `
        --cpu $CPU `
        --port $PORT `
        --timeout $TIMEOUT `
        --min-instances 0 `
        --quiet 2>&1 | ForEach-Object { Note $_ }

    if ($LASTEXITCODE -eq 0) {
        $url = (gcloud run services describe $svc.Name --region $Region --format="value(status.url)" 2>$null)
        Ok "deployed: $url"
    } else {
        Bad "deploy failed for $($svc.Name)"
        $failed++
    }
}

# ---------------------------------------------------------------- verdict

Step "Result"
if ($failed -eq 0) {
    Write-Host "  Both services deployed." -ForegroundColor Green
    gcloud run services list --region $Region --format="table(SERVICE,URL)" 2>&1 |
        ForEach-Object { Note $_ }
    Write-Host ""
    Write-Host "  Check each one answers before relying on it:"
    Write-Host "    curl <url>/api/health"
    Write-Host ""
    Write-Host "  min-instances is 0, so the first request after an idle period pays a"
    Write-Host "  cold start of roughly 20-30 seconds. Before the demo, either open both"
    Write-Host "  URLs ten minutes early or set --min-instances 1 for the day."
    exit 0
}
Write-Host "  $failed deploy(s) failed - the gcloud output above says why." -ForegroundColor Red
exit 1
