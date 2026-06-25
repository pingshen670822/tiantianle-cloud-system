$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
$RepoName = "tiantianle-cloud-system"
$env:GH_CONFIG_DIR = Join-Path $ScriptDir ".gh-cli"
New-Item -ItemType Directory -Path $env:GH_CONFIG_DIR -Force | Out-Null

function Refresh-Path {
  $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $user = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = $machine + ";" + $user
}

function Ensure-Command {
  param([string]$Name, [string]$PackageId)
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
      throw "Windows Package Manager is required to install $Name."
    }
    winget install --id $PackageId -e --accept-package-agreements --accept-source-agreements
    Refresh-Path
  }
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "$Name is not available after installation."
  }
}

function Get-PythonCommand {
  $bundled = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path $bundled) {
    return $bundled
  }
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    return $python.Source
  }
  Ensure-Command "python" "Python.Python.3.12"
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    return $python.Source
  }
  throw "Python is not available."
}

function Test-GhAuthentication {
  $previousPreference = $ErrorActionPreference
  $ErrorActionPreference = "SilentlyContinue"
  & gh auth status *> $null
  $authenticated = $LASTEXITCODE -eq 0
  $ErrorActionPreference = $previousPreference
  return $authenticated
}

function Repair-GhAuthentication {
  $previousPreference = $ErrorActionPreference
  $ErrorActionPreference = "SilentlyContinue"
  $statusText = (& gh auth status 2>&1 | Out-String)
  $ErrorActionPreference = $previousPreference
  if ($statusText -match "account\s+([A-Za-z0-9_.-]+)") {
    $badUser = $Matches[1]
    Write-Host "Clearing expired GitHub CLI login for $badUser..."
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    & gh auth logout -h github.com -u $badUser *> $null
    $ErrorActionPreference = $previousPreference
  }
  Write-Host "A GitHub official login page will open. Please approve the login."
  gh auth login -h github.com --web --git-protocol https
  if ($LASTEXITCODE -ne 0) {
    throw "GitHub login was not completed."
  }
  if (-not (Test-GhAuthentication)) {
    throw "GitHub login is still invalid."
  }
}

function Test-GhRepository {
  param([string]$Repository)
  $previousPreference = $ErrorActionPreference
  $ErrorActionPreference = "SilentlyContinue"
  gh repo view $Repository --json name *> $null
  $exists = $LASTEXITCODE -eq 0
  $ErrorActionPreference = $previousPreference
  return $exists
}

function Copy-TreeWithoutGit {
  param([string]$From, [string]$To)
  New-Item -ItemType Directory -Path $To -Force | Out-Null
  Get-ChildItem -LiteralPath $To -Force | Where-Object { $_.Name -ne ".git" -and $_.Name -ne ".gh-cli" -and $_.Name -ne "__pycache__" } | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Recurse -Force
  }
  Get-ChildItem -LiteralPath $From -Force | Where-Object { $_.Name -ne ".git" -and $_.Name -ne ".gh-cli" -and $_.Name -ne "__pycache__" } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $To -Recurse -Force
  }
}

Write-Host "Preparing Tiantianle cloud mobile system..."
Ensure-Command "git" "Git.Git"
Ensure-Command "gh" "GitHub.cli"
$PythonExe = Get-PythonCommand
git config --global --add safe.directory $ScriptDir

if (-not (Test-GhAuthentication)) {
  Repair-GhAuthentication
}

$Owner = gh api user --jq .login
$FullRepo = "$Owner/$RepoName"
$env:GITHUB_REPOSITORY = $FullRepo

Write-Host "Rebuilding mobile site..."
& $PythonExe california_fantasy5_system.py
if ($LASTEXITCODE -ne 0) { throw "System update failed." }
& $PythonExe pages_build.py
if ($LASTEXITCODE -ne 0) { throw "Site build failed." }

if (-not (Test-GhRepository $FullRepo)) {
  if (-not (Test-Path ".git")) {
    git init
  }
  git checkout -B main
  git config user.name "$Owner"
  git config user.email "$Owner@users.noreply.github.com"
  git add .
  git commit -m "Create Tiantianle cloud mobile system"
  gh repo create $RepoName --public --source . --remote origin --push
} else {
  $PayloadCopy = Join-Path $env:TEMP ("tiantianle-cloud-payload-" + [guid]::NewGuid().ToString("N"))
  Copy-TreeWithoutGit $ScriptDir $PayloadCopy
  if (-not (Test-Path ".git")) {
    git init
    git remote add origin "https://github.com/$FullRepo.git"
  }
  git fetch origin main
  git checkout -B main origin/main
  Copy-TreeWithoutGit $PayloadCopy $ScriptDir
  Remove-Item -LiteralPath $PayloadCopy -Recurse -Force
  git config user.name "$Owner"
  git config user.email "$Owner@users.noreply.github.com"
  git add .
  git diff --cached --quiet
  if ($LASTEXITCODE -ne 0) {
    git commit -m "Update Tiantianle cloud mobile system"
  }
  git push -u origin main
}

try {
  gh api "repos/$FullRepo/pages" -X POST -f build_type=workflow | Out-Null
} catch {
  Write-Host "GitHub Pages already exists or will be enabled by the workflow."
}

$PageUrl = "https://$Owner.github.io/$RepoName/"
$UrlFile = Join-Path $ScriptDir "tiantianle-mobile-cloud-url.txt"
Set-Content -Path $UrlFile -Value $PageUrl -Encoding ASCII

Write-Host ""
Write-Host "Starting first cloud update and deployment..."
gh workflow run daily-update.yml --repo $FullRepo
Start-Sleep -Seconds 5
$RunId = gh run list --repo $FullRepo --workflow daily-update.yml --limit 1 --json databaseId --jq ".[0].databaseId"
if ($RunId) {
  gh run watch $RunId --repo $FullRepo --exit-status
  if ($LASTEXITCODE -ne 0) {
    Start-Process "https://github.com/$FullRepo/actions"
    throw "First GitHub Pages deployment failed."
  }
}

Write-Host ""
Write-Host "Tiantianle cloud mobile system is online:"
Write-Host $PageUrl
Start-Process $PageUrl
