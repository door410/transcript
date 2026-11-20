# transcript - Windows one-line install / update. PURE ASCII ONLY.
#
#   irm https://raw.githubusercontent.com/door410/transcript/main/install.ps1 | iex
#
# First run : installs Python + Git if missing (winget), clones to
#             %USERPROFILE%\transcript, runs the setup .bat, makes the desktop shortcut.
# Later runs: git pull + refresh the desktop shortcut. Same command.
# Two versions: branch 'main' (URLs only) and 'local-files' (also local files).
# Each branch's copy of this file sets $Branch to itself, so running the other
# branch's command switches the installed copy to that version.
$ErrorActionPreference = 'Continue'
$Branch = 'main'
$Repo = 'https://github.com/door410/transcript.git'
$Dir  = Join-Path $env:USERPROFILE 'transcript'
$Old  = Join-Path $env:USERPROFILE 'yt-transcript'

function Say($m) { Write-Host "  $m" }
function RefreshPath {
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
              [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Has($cmd) {
  try { & $cmd --version *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}

Write-Host ''
Say '=== transcript ==='

# Old folder name from earlier versions -> rename once.
if (-not (Test-Path $Dir) -and (Test-Path (Join-Path $Old '.git'))) {
  Say "Renaming $Old -> $Dir"
  Rename-Item $Old $Dir
}

if (-not (Has 'git')) {
  Say 'Installing Git...'
  winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements
  RefreshPath
}
if (-not (Has 'python')) {
  Say 'Installing Python 3.12...'
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements `
    --override '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1'
  RefreshPath
}
if (-not (Has 'git') -or -not (Has 'python')) {
  Say '[ERROR] Git or Python still not found. Close this window, open a new'
  Say 'PowerShell and run the same command again.'
  return
}

if (Test-Path (Join-Path $Dir '.git')) {
  Say "Updating ($Branch)..."
  git -C $Dir fetch origin
  $cur = git -C $Dir rev-parse --abbrev-ref HEAD
  if ($cur -ne $Branch) {
    Say "Switching version: $cur -> $Branch"
    git -C $Dir checkout $Branch
    if ($LASTEXITCODE -ne 0) { Say '[ERROR] switch failed (see message above).'; return }
  }
  git -C $Dir pull --ff-only
  if ($LASTEXITCODE -ne 0) { Say '[ERROR] git pull failed (see message above).'; return }
  python -m pip install --quiet --upgrade -r (Join-Path $Dir 'requirements\core.txt')
  cscript //nologo (Join-Path $Dir 'make_shortcut.vbs')
  Say 'Done. Close the app if it is open, then start it again from the'
  Say 'desktop shortcut "transcript".'
} else {
  Say "Downloading to $Dir ..."
  git clone -b $Branch $Repo $Dir
  if ($LASTEXITCODE -ne 0) { Say '[ERROR] git clone failed.'; return }
  # The setup .bat has a Chinese file name; pick it by its pure-ASCII marker line.
  $bat = Get-ChildItem $Dir -Filter *.bat |
         Where-Object { Select-String -Path $_.FullName -Pattern 'Tool - Setup|transcript - Setup' -Quiet } |
         Select-Object -First 1
  Set-Location $Dir
  cmd /c "`"$($bat.FullName)`""
}
