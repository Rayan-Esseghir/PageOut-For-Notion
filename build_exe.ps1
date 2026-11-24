# ============================================================
#  PageOut for Notion – PyInstaller build script (PowerShell)
# ============================================================
#
#  Prerequisites:
#    pip install pyinstaller pillow
#    pip install notion-client playwright pypdf python-docx
#    playwright install chromium
#
#  Run from the project root:
#    .\build_exe.ps1
# ============================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "============================================================"
Write-Host "  PageOut for Notion | PyInstaller build"
Write-Host "============================================================"
Write-Host ""

# ── Check prerequisites ──────────────────────────────────────────────────────
if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Error "pyinstaller not found on PATH.`nRun: pip install pyinstaller"
}

# ── Locate icon ──────────────────────────────────────────────────────────────
$iconArg = @()
if (Test-Path "icon.ico") {
    $iconArg = @("--icon=icon.ico")
    Write-Host "[INFO] Using icon.ico"
} elseif (Test-Path "icon.png") {
    $iconArg = @("--icon=icon.png")
    Write-Host "[INFO] Using icon.png (PyInstaller will convert to .ico)"
} else {
    Write-Host "[INFO] No .ico/.png icon found; app will use programmatic icon at runtime."
}

# ── Collect --add-data for icon files that exist ─────────────────────────────
$addData = @()
foreach ($f in @("icon.ico", "icon.png", "icon.jpg")) {
    if (Test-Path $f) {
        $addData += "--add-data=$f;."
    }
}

# ── Playwright Chromium note ─────────────────────────────────────────────────
Write-Host ""
Write-Host "[INFO] Playwright Chromium:"
Write-Host "  The Browser PDF engine requires Chromium."
Write-Host "  To use it on another PC after distributing the .exe:"
Write-Host "    Option A) Run 'playwright install chromium' on that machine."
Write-Host "    Option B) Copy the Chromium folder and set env:"
Write-Host "              `$env:PLAYWRIGHT_BROWSERS_PATH = 'C:\path\to\browsers'"
Write-Host "  The API engine (default) requires NO browser at all."
Write-Host ""

# ── PyInstaller arguments ─────────────────────────────────────────────────────
$pyiArgs = @(
    "--onefile",
    "--windowed",                       # no console window (remove for debug)
    "--name=PageOut-for-Notion",
    # Resource files bundled into the .exe
    "--add-data=notion_exporter.py;.",
    # Icons (only the ones that exist, added above)
) + $addData + $iconArg + @(
    # Force-include runtime imports PyInstaller may miss
    "--hidden-import=notion_client",
    "--hidden-import=playwright",
    "--hidden-import=playwright.sync_api",
    "--hidden-import=pypdf",
    "--hidden-import=docx",
    "--hidden-import=PIL",
    "--hidden-import=PIL.Image",
    "--hidden-import=PIL.ImageDraw",
    "--hidden-import=PIL.ImageFont",
    "--hidden-import=PIL.ImageTk",
    "notion_exporter.py"
)

Write-Host "[BUILD] Running: pyinstaller $pyiArgs"
Write-Host ""

& pyinstaller @pyiArgs

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed (exit code $LASTEXITCODE)."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "  Build complete!"
Write-Host "  Output: dist\PageOut-for-Notion.exe"
Write-Host "============================================================"
Write-Host ""
