# Dikte installer (Windows): dependency check, launchers, autostart.
# Mirrors install.sh for the Windows desktop: no global-shortcut files to write,
# because Windows has no shortcut registry and Dikte's built-in RegisterHotKey
# listener is the only way the keys arrive. It runs automatically there.

$ErrorActionPreference = "Stop"

$DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$PY = (Get-Command python -ErrorAction SilentlyContinue)
$STARTPATH = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"
$RUNKEY = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

function say  { Write-Host "  $args" }
function ok   { Write-Host "  $([char]0x2713) $args" }
function warn { Write-Host "  $([char]0x0021) $args" -ForegroundColor Yellow }

Write-Host ""
Write-Host "Installing Dikte"
Write-Host "`u{2500}" * 16

# 1. Dependencies ----------------------------------------------------------
$missing = @()
if (-not $PY) { $missing += "python (install from python.org, tick 'Add to PATH')" }
if ($PY) {
  & python -c "import PyQt6.QtWidgets" 2>$null
  if ($LASTEXITCODE -ne 0) { $missing += "python-pyqt6 (pip install PyQt6)" }
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  $missing += "ffmpeg (winget install Gyan.FFmpeg)"
}
if ($missing.Count) {
  warn "Missing: $($missing -join ', ')"
} else {
  ok "All dependencies present"
}

# 2. The launcher ----------------------------------------------------------
# `dikte` on a command line, and the desktop shortcuts that point at it.
$LAUNCHER = Join-Path $DIR "dikte.cmd"
if (-not (Test-Path -LiteralPath $LAUNCHER)) {
  Set-Content -LiteralPath $LAUNCHER -Value "@echo off`r`npython `"%~dp0dikte.py`" %*`r`n" -Encoding ASCII
  ok "Launcher created: $LAUNCHER"
}

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -split ";" -notcontains $DIR) {
  [Environment]::SetEnvironmentVariable("Path", "$userPath;$DIR", "User")
  warn "Added $DIR to your PATH; it works from a new terminal."
} else {
  ok "Already on your PATH"
}

$menuDir = Join-Path $STARTPATH "Dikte"
New-Item -ItemType Directory -Force -Path $menuDir | Out-Null
$lnk = Join-Path $menuDir "Dikte.lnk"
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($lnk)
$shortcut.TargetPath = $LAUNCHER
$shortcut.WorkingDirectory = $DIR
$shortcut.Description = "Voice dictation: record, transcribe, clean up, paste"
$shortcut.IconLocation = "imageres.dll,78"
$shortcut.Save()
ok "Start menu entry added: $lnk"

# 3. Autostart -------------------------------------------------------------
# pythonw so no console window appears at login.
$pythonw = Join-Path (Split-Path (Get-Command python).Path) "pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw)) { $pythonw = (Get-Command python).Path }
New-ItemProperty -Path $RUNKEY -Name "Dikte" -Value "`"$pythonw`" `"$DIR\dikte.py`"" -PropertyType String -Force | Out-Null
ok "Will start automatically on login"

# 4. Shortcuts -------------------------------------------------------------
# Windows has no KDE/GNOME shortcut registry to write. Dikte's built-in
# listener (RegisterHotKey) is what delivers the keys, and on Windows it runs
# always. The combinations are the `shortcut` and `cancel_shortcut` settings.
say "Keys arrive through the built-in listener, which is always on here."
say "Change them in Settings -> Shortcuts (defaults: Ctrl+Space, Ctrl+Alt+Space)."

Write-Host ""
ok "Done. Start it with:  dikte"
say "The settings window opens on first run: download a speech model, or add"
say "an OpenAI or OpenRouter key instead."
Write-Host ""