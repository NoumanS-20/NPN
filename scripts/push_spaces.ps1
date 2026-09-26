# Push the staged Hugging Face Spaces, from Windows PowerShell.
#
#     powershell -ExecutionPolicy Bypass -File scripts\push_spaces.ps1
#     powershell -ExecutionPolicy Bypass -File scripts\push_spaces.ps1 -App pr1
#
# Why this exists rather than a handful of commands: Windows PowerShell 5.1 has
# no "&&" operator and does not understand /c/... paths, so the obvious one-liner
# fails before it runs anything. This does each step in order, checks it worked,
# and stops at the first real problem with a message that says what to do.
#
# The Space must already exist. Create it at https://huggingface.co/new-space
# (any SDK — the README we push sets it to Docker).

param(
    [ValidateSet("pr1", "p2", "both")]
    [string]$App = "both"
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot

$spaces = @{
    pr1 = @{ Dir = "build\spaces\pr1"; Repo = "Nouman-20/supplyguard";        Name = "SupplyGuard" }
    p2  = @{ Dir = "build\spaces\p2";  Repo = "Nouman-20/trendwear-planner";  Name = "TrendWear Planner" }
}

function Step($m) { Write-Host "`n=== $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  ok    $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  FAIL  $m" -ForegroundColor Red }
function Note($m) { Write-Host "        $m" -ForegroundColor DarkGray }

# ---------------------------------------------------------------- the token

# Read it from the gitignored .env rather than asking anyone to paste a secret
# into a terminal, where it would sit in the shell history. It is used for this
# push only and is never written into .git/config.
$token = $null
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*HF_TOKEN\s*=\s*(.+?)\s*$') { $token = $Matches[1].Trim('"').Trim("'") }
    }
}
if ($token) {
    Ok "found HF_TOKEN in .env (used for this push only, not saved to .git/config)"
} else {
    Note "No HF_TOKEN in .env - git will prompt for your write token instead."
}

$targets = if ($App -eq "both") { @("pr1", "p2") } else { @($App) }
$failed = 0

foreach ($key in $targets) {
    $space = $spaces[$key]
    $dir = Join-Path $root $space.Dir

    Step "$($space.Name)  ->  $($space.Repo)"

    if (-not (Test-Path $dir)) {
        Bad "$dir does not exist."
        Note "Stage it first:  .venv\Scripts\python.exe scripts\stage_space.py $key --force"
        $failed++
        continue
    }
    Set-Location $dir

    # A previous half-finished attempt leaves a .git behind; start clean so the
    # history is always a single deploy commit.
    if (Test-Path ".git") {
        Remove-Item -Recurse -Force ".git"
        Note "removed a .git from an earlier attempt"
    }

    git init -q -b main
    if ($LASTEXITCODE -ne 0) { Bad "git init failed"; $failed++; continue }

    git lfs install --local | Out-Null
    if ($LASTEXITCODE -ne 0) { Bad "git lfs install failed - is Git LFS installed?"; $failed++; continue }
    Ok "repository initialised with LFS"

    git add -A
    if ($LASTEXITCODE -ne 0) { Bad "git add failed"; $failed++; continue }

    git -c user.email="deploy@vortex5.invalid" -c user.name="Vortex5" commit -q -m "deploy"
    if ($LASTEXITCODE -ne 0) { Bad "git commit failed"; $failed++; continue }

    # Anything over 10 MB must be an LFS pointer or Hugging Face refuses the push.
    $big = Get-ChildItem -Recurse -File | Where-Object { $_.Length -gt 10MB }
    $tracked = @(git lfs ls-files)
    foreach ($f in $big) {
        $rel = $f.FullName.Substring($dir.Length + 1).Replace('\', '/')
        if (-not ($tracked -match [regex]::Escape($f.Name))) {
            Bad "$rel is $([math]::Round($f.Length/1MB)) MB and is NOT tracked by LFS - the push would be rejected."
            $failed++
        }
    }
    if ($big) { Ok "$($tracked.Count) file(s) tracked by LFS, including the $([math]::Round(($big | Measure-Object Length -Maximum).Maximum/1MB)) MB model" }

    $url = if ($token) { "https://user:$token@huggingface.co/spaces/$($space.Repo)" }
           else        { "https://huggingface.co/spaces/$($space.Repo)" }

    Step "pushing $(( Get-ChildItem -Recurse -File | Measure-Object ).Count) files - the 30 MB model takes a minute"
    git push --force $url main 2>&1 | ForEach-Object { Note $_ }

    if ($LASTEXITCODE -eq 0) {
        Ok "pushed to $($space.Repo)"
        Note "watch it build: https://huggingface.co/spaces/$($space.Repo)"
    } else {
        Bad "push failed for $($space.Repo)"
        Note "401/403 -> the token is not a WRITE token, or it has expired."
        Note "404     -> the Space does not exist yet: https://huggingface.co/new-space"
        $failed++
    }
}

Set-Location $root
Step "Result"
if ($failed -eq 0) {
    Write-Host "  Both Spaces pushed. They build in a few minutes." -ForegroundColor Green
    Write-Host "  https://nouman-20-supplyguard.hf.space"
    Write-Host "  https://nouman-20-trendwear-planner.hf.space"
    exit 0
}
Write-Host "  $failed step(s) failed - see the messages above." -ForegroundColor Red
exit 1
