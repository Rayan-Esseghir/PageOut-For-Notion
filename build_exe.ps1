# ============================================================
#  PageOut for Notion - PyInstaller build script (PowerShell)
# ============================================================
#  Prerequisites:
#    pip install -r requirements.txt pyinstaller
#    playwright install chromium        (only needed for the Browser PDF engine)
#
#  Run from the project root:   .\build_exe.ps1
#  Debug build (shows console): .\build_exe.ps1 -Console
# ============================================================
param([switch]$Console)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "============================================================"
Write-Host "  PageOut for Notion | PyInstaller build"
Write-Host "============================================================"

# -- prerequisites ------------------------------------------------------
& python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) { throw "PyInstaller not found. Run: pip install pyinstaller" }
if (-not (Test-Path "notion_exporter.py")) { throw "Run this script from the project folder." }

# -- icon (exe icon + bundled copy for the window/taskbar icon) ---------
$iconArgs = @()
if (Test-Path "icon.ico") {
    $iconArgs += "--icon=icon.ico"
    Write-Host "[INFO] Using icon.ico"
} else {
    Write-Warning "icon.ico not found - the exe will use the default icon."
}
foreach ($f in @("icon.ico", "icon.png")) {
    if (Test-Path $f) { $iconArgs += "--add-data=$f;." }
}

# -- arguments ----------------------------------------------------------
$pyiArgs = @(
    "--noconfirm", "--clean",
    "--onefile",
    "--name=PageOut-for-Notion"
)
if (-not $Console) { $pyiArgs += "--windowed" }
$pyiArgs += $iconArgs
$pyiArgs += @(
    # packages with data files / drivers that PyInstaller cannot see on its own
    "--collect-all=playwright",      # bundled Node driver
    "--collect-all=google.genai",
    "--collect-data=docx",           # python-docx default template
    "--hidden-import=notion_client",
    "--hidden-import=pypdf",
    "--hidden-import=PIL.ImageTk",
    "notion_exporter.py"
)

Write-Host "[BUILD] python -m PyInstaller $($pyiArgs -join ' ')"
& python -m PyInstaller @pyiArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed (exit code $LASTEXITCODE)." }

Write-Host ""
Write-Host "============================================================"
Write-Host "  Build complete:  dist\PageOut-for-Notion.exe"
Write-Host "============================================================"
Write-Host "  Browser PDF engine needs Chromium on the target PC:"
Write-Host "    a) run 'playwright install chromium' there, or"
Write-Host "    b) copy your ms-playwright folder next to the .exe and"
Write-Host "       rename it to 'browsers' (the app picks it up automatically)."
Write-Host "  The API engine (default) needs no browser."
Write-Host ""
