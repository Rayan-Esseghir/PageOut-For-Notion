@echo off
REM ============================================================
REM  PageOut for Notion - PyInstaller build script (Windows CMD)
REM ============================================================
REM  Prerequisites:
REM    pip install -r requirements.txt pyinstaller
REM    playwright install chromium   (only for the Browser PDF engine)
REM
REM  Run from the project root:   build_exe.bat
REM  Debug build (shows console): build_exe.bat console
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   PageOut for Notion ^| PyInstaller build
echo ============================================================

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller not found.  Run:  pip install pyinstaller
    exit /b 1
)
if not exist notion_exporter.py (
    echo [ERROR] Run this script from the project folder.
    exit /b 1
)

set "WIN_OPT=--windowed"
if /i "%~1"=="console" set "WIN_OPT="

set "ICON_OPT="
set "DATA_OPT="
if exist icon.ico (
    set "ICON_OPT=--icon=icon.ico"
    set "DATA_OPT=--add-data icon.ico;."
    echo [INFO] Using icon.ico
) else (
    echo [WARN] icon.ico not found - default icon will be used.
)
if exist icon.png set "DATA_OPT=%DATA_OPT% --add-data icon.png;."

if not exist pageout\assets\katex\katex.min.js (
    echo [ERROR] pageout\assets\katex is missing - run tools\vendor_katex.py
    exit /b 1
)

python -m PyInstaller --noconfirm --clean --onefile %WIN_OPT% ^
  --name PageOut-for-Notion ^
  %ICON_OPT% %DATA_OPT% ^
  --add-data "pageout/assets;pageout/assets" ^
  --collect-submodules pageout ^
  --collect-all keyring ^
  --hidden-import yaml ^
  --collect-all playwright ^
  --collect-all google.genai ^
  --collect-data docx ^
  --hidden-import notion_client ^
  --hidden-import pypdf ^
  --hidden-import PIL.ImageTk ^
  notion_exporter.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.  See above for details.
    exit /b 1
)

echo.
echo ============================================================
echo   Build complete:  dist\PageOut-for-Notion.exe
echo ============================================================
echo   Browser PDF engine needs Chromium on the target PC:
echo     a^) run "playwright install chromium" there, or
echo     b^) copy your ms-playwright folder next to the .exe and
echo        rename it to "browsers" (picked up automatically).
echo   The API engine (default) needs no browser.
echo.
endlocal
