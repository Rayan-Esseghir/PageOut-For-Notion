@echo off
REM ============================================================
REM  PageOut for Notion – PyInstaller build script (Windows)
REM ============================================================
REM
REM  Prerequisites:
REM    pip install pyinstaller pillow
REM    pip install notion-client playwright pypdf python-docx
REM    playwright install chromium
REM
REM  Run from the project root:
REM    build_exe.bat
REM ============================================================

setlocal EnableDelayedExpansion

echo.
echo ============================================================
echo   PageOut for Notion ^| PyInstaller build
echo ============================================================
echo.

REM ── Locate pyinstaller ──
where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pyinstaller not found on PATH.
    echo         Run:  pip install pyinstaller
    exit /b 1
)

REM ── Locate icon ──
set ICON_OPT=
if exist "icon.ico" (
    set ICON_OPT=--icon=icon.ico
    echo [INFO] Using icon.ico
) else if exist "icon.png" (
    set ICON_OPT=--icon=icon.png
    echo [INFO] Using icon.png
) else if exist "icon.jpg" (
    echo [INFO] No .ico found; app will use programmatic icon at runtime.
)

REM ── Find the Playwright Chromium executable for bundling ──
REM
REM  Playwright stores Chromium under the user's home directory.
REM  We detect it here and pass it as an extra --add-binary so the
REM  .exe can launch Chromium (Browser engine).  If you don't need
REM  the Browser engine, delete the lines between CUT-START and CUT-END.
REM
REM  NOTE: Bundling the full Chromium (~300 MB) will make the .exe very large.
REM  Alternative: distribute Chromium separately and set PLAYWRIGHT_BROWSERS_PATH
REM  to its parent directory before launching the .exe.
REM
REM CUT-START  ─────────────────────────────────────────────────
set PW_CHROME=
for /f "delims=" %%D in ('python -c "import os,pathlib; bdir=pathlib.Path.home()/'.cache'/'ms-playwright'; print([str(p) for p in bdir.rglob('chrome.exe') if p.exists()][0] if bdir.exists() else '')" 2^>nul') do (
    set PW_CHROME=%%D
)
if defined PW_CHROME (
    echo [INFO] Playwright Chromium: !PW_CHROME!
    echo [INFO] Chromium will NOT be bundled – set PLAYWRIGHT_BROWSERS_PATH
    echo        to its parent folder before running the .exe, or use API engine.
) else (
    echo [INFO] Playwright Chromium not found locally; Browser engine will need
    echo        PLAYWRIGHT_BROWSERS_PATH set at runtime.
)
REM CUT-END  ───────────────────────────────────────────────────

REM ── PyInstaller command ──
REM
REM  --onefile            Single .exe (slower startup but easier to distribute)
REM  --windowed           No console window (use --console for debugging)
REM  --name               Output exe name
REM  --add-data           Bundle icon files so resource_path() finds them
REM  --hidden-import      Force-include modules PyInstaller can miss
REM
pyinstaller ^
  --onefile ^
  --windowed ^
  --name "PageOut-for-Notion" ^
  %ICON_OPT% ^
  --add-data "notion_exporter.py;." ^
  --add-data "icon.ico;."  2>nul ^& echo. ^
  --add-data "icon.png;."  2>nul ^& echo. ^
  --add-data "icon.jpg;."  2>nul ^& echo. ^
  --hidden-import "notion_client" ^
  --hidden-import "playwright" ^
  --hidden-import "playwright.sync_api" ^
  --hidden-import "pypdf" ^
  --hidden-import "docx" ^
  --hidden-import "PIL" ^
  --hidden-import "PIL.Image" ^
  --hidden-import "PIL.ImageDraw" ^
  --hidden-import "PIL.ImageFont" ^
  --hidden-import "PIL.ImageTk" ^
  notion_exporter.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.  See above for details.
    exit /b 1
)

echo.
echo ============================================================
echo   Build complete!   dist\PageOut-for-Notion.exe
echo ============================================================
echo.
echo   PLAYWRIGHT NOTE:
echo   The Browser PDF engine requires Chromium.  When running the
echo   .exe on another PC, either:
echo     a) Run:  playwright install chromium  (on that machine)
echo     b) Copy the Chromium folder and set:
echo           set PLAYWRIGHT_BROWSERS_PATH=C:\path\to\browsers
echo        before launching the .exe.
echo   The API engine (default) needs no browser at all.
echo.
endlocal
