# Dikte updater (Windows): pull, put the launchers back, restart what was
# running. Mirrors update.sh; works from a git checkout.

$ErrorActionPreference = "Stop"

$DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

function say  { Write-Host "  $args" }
function ok   { Write-Host "  $([char]0x2713) $args" }
function warn { Write-Host "  $([char]0x0021) $args" -ForegroundColor Yellow }
function die  { Write-Host "  $([char]0x2717) $args" -ForegroundColor Red; Write-Host ""; exit 1 }

Write-Host ""
Write-Host "Updating Dikte"
Write-Host "`u{2500}" * 14

# 1. Somewhere there is something to pull ----------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  die "git not found; update by downloading the source again"
}
Set-Location $DIR
if (-not (Test-Path -LiteralPath "$DIR\.git")) {
  die "$DIR is not a git checkout; update by downloading the source again"
}

$before = & git rev-parse HEAD

# 2. Is there anything to come? ---------------------------------------------
& git fetch --quiet 2>$null
if ($LASTEXITCODE -ne 0) { die "Could not reach the remote." }
$upstream = & git rev-parse "@{u}" 2>$null
if ($LASTEXITCODE -ne 0) { die "This branch is not tracking a remote one; pull by hand." }

if ($before -eq $upstream) {
  Write-Host ""
  ok "Already up to date ($(& git log -1 --format=%s))"
  Write-Host ""
  exit 0
}

# 3. Only now, your own edits -----------------------------------------------
if (& git status --porcelain) {
  warn "There is an update waiting, but you have changes of your own here:"
  & git --no-pager status --short | ForEach-Object { Write-Host "    $_" }
  say "Commit them, or put them aside with:  git stash --include-untracked"
  die "Nothing was updated."
}

& git merge --ff-only "@{u}" 2>$null
if ($LASTEXITCODE -ne 0) {
  say "Your branch has commits the remote does not. To put them on top of the"
  say "update instead:  git pull --rebase"
  die "Could not fast-forward."
}
$after = & git rev-parse HEAD

Write-Host ""
say "What arrived:"
& git log --oneline "$before..$after" | ForEach-Object { Write-Host "    $_" }
Write-Host ""

# 4. Launchers --------------------------------------------------------------
# An update can add a dependency or move a file, so the installer runs again.
& "$DIR\install.ps1"

# 5. The running instance ---------------------------------------------------
# It is still running the code from before the pull.
& python "$DIR\dikte.py" status 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
  if (& python "$DIR\dikte.py" restart 2>$null) {
    ok "Restarted, so the new version is the one running"
  } else {
    warn "Could not restart it; use the tray menu -> Restart"
  }
} else {
  say "Dikte was not running. Start it with:  dikte"
}
Write-Host ""