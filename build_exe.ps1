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
$iconPath = "pageout/assets/icon.ico"
if (Test-Path $iconPath) {
    Write-Host "[INFO] Using $iconPath"
} else {
    Write-Warning "icon.ico not found - the exe will use the default icon."
}

# -- bundled assets (offline KaTeX) --------------------------------------
if (-not (Test-Path "pageout/assets/katex/katex.min.js")) { throw "pageout/assets/katex is missing (run tools/vendor_katex.py)." }

# -- build using spec file ------------------------------------------------
$pyiArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name=PageOut-for-Notion"
)
if (-not $Console) { $pyiArgs += "--windowed" }
# Use spec file for cleaner build configuration
if (Test-Path $iconPath) {
    $pyiArgs += "--icon=$iconPath"
}
# Add assets with proper quoting for Windows
$pyiArgs += "--add-data=pageout/assets;pageout/assets"
$pyiArgs += "--collect-submodules=pageout"
$pyiArgs += "--collect-all=keyring"
$pyiArgs += "--hidden-import=yaml"
$pyiArgs += "--collect-all=playwright"
$pyiArgs += "--collect-all=google.genai"
$pyiArgs += "--collect-data=docx"
$pyiArgs += "--hidden-import=notion_client"
$pyiArgs += "--hidden-import=pypdf"
$pyiArgs += "--hidden-import=PIL.ImageTk"
$pyiArgs += "notion_exporter.py"

# Join arguments with proper escaping for PowerShell
$argStrings = $pyiArgs | ForEach-Object { "`"$_`"" }
$joinedArgs = $argStrings -join " "

Write-Host "[BUILD] python -m PyInstaller $joinedArgs"
& python -m PyInstaller $pyiArgs
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