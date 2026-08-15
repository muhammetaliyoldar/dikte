# Dikte uninstaller (Windows): takes back what install.ps1 put down, and
# nothing else unless asked. Your settings and your dictations survive a plain
# run; --purge is the word that deletes them.

param(
  [switch]$Purge,
  [switch]$Yes
)

$DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$STARTPATH = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"
$RUNKEY = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$CONFIG_DIR = Join-Path $env:APPDATA "Dikte"       # settings, dictations, meetings
$MODELS_DIR = Join-Path $env:LOCALAPPDATA "Dikte"  # downloaded programs and models

function say  { Write-Host "  $args" }
function ok   { Write-Host "  $([char]0x2713) $args" }
function warn { Write-Host "  $([char]0x0021) $args" -ForegroundColor Yellow }
function gone { Write-Host "  $([char]0x00B7) $args" -ForegroundColor DarkGray }

Write-Host ""
Write-Host "Uninstalling Dikte"
Write-Host "`u{2500}" * 18

# 1. The running instance --------------------------------------------------
& python "$DIR\dikte.py" quit 2>$null | Out-Null
Start-Sleep -Milliseconds 500

# 2. Launchers -------------------------------------------------------------
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -split ";" -contains $DIR) {
  $rest = @($userPath -split ";" | Where-Object { $_ -ne $DIR }) -join ";"
  [Environment]::SetEnvironmentVariable("Path", $rest, "User")
  ok "Removed $DIR from your PATH"
} else {
  gone "Was not on your PATH: $DIR"
}

$menuDir = Join-Path $STARTPATH "Dikte"
$lnk = Join-Path $menuDir "Dikte.lnk"
if (Test-Path -LiteralPath $lnk) {
  Remove-Item -LiteralPath $lnk -Force
  ok "Removed $lnk"
} else {
  gone "Was not there: $lnk"
}
if ((Test-Path -LiteralPath $menuDir) -and -not (Get-ChildItem -LiteralPath $menuDir)) {
  Remove-Item -LiteralPath $menuDir -Force
}

if (Get-ItemProperty -Path $RUNKEY -Name "Dikte" -ErrorAction SilentlyContinue) {
  Remove-ItemProperty -Path $RUNKEY -Name "Dikte"
  ok "Removed the autostart entry"
} else {
  gone "Was not there: the autostart entry"
}

# 3. Settings, dictations and downloaded models ------------------------------
Write-Host ""
if ($Purge) {
  warn "--purge also deletes:"
  say $CONFIG_DIR
  say $MODELS_DIR
  if (-not $Yes) {
    $reply = Read-Host "  Type yes to delete them"
    if ($reply -ne "yes") { $Purge = $false; say "Kept." }
  }
}

if ($Purge) {
  Remove-Item -LiteralPath $CONFIG_DIR -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $MODELS_DIR -Recurse -Force -ErrorAction SilentlyContinue
  ok "Settings, dictations and downloaded models deleted"
} else {
  say "Settings kept:     $CONFIG_DIR"
  say "Models kept:       $MODELS_DIR"
  say "Delete them too with:  .\uninstall.ps1 -Purge"
}

Write-Host ""
ok "Done."
say "The source directory is untouched: $DIR"
Write-Host ""