@echo off
REM TEE yt-dlp Downloader - First-time installer.
REM Erstellt ein lokales venv und laedt alle Abhaengigkeiten.

cd /d "%~dp0"
title TEE yt-dlp - Installer

echo ===============================================
echo TEE yt-dlp Downloader - Erstinstallation
echo ===============================================
echo.

REM ---- Python-Check ----------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo [FEHLER] Python wurde nicht gefunden!
    echo.
    echo  Bitte installiere Python 3.11 oder hoeher:
    echo    https://www.python.org/downloads/
    echo.
    echo  WICHTIG beim Setup:  "Add Python to PATH" anhaken!
    echo.
    pause
    exit /b 1
)

python --version
echo.

REM ---- venv anlegen ---------------------------------------------------
if not exist "venv\Scripts\python.exe" (
    echo [1/5] Erstelle Python venv...
    python -m venv venv
    if errorlevel 1 (
        echo [FEHLER] venv konnte nicht erstellt werden.
        pause
        exit /b 1
    )
) else (
    echo [1/5] venv existiert bereits - skip.
)

REM ---- pip upgraden + Pakete installieren -----------------------------
echo.
echo [2/5] Upgrade pip...
"venv\Scripts\python.exe" -m pip install --upgrade pip --quiet

echo.
echo [3/5] Installiere yt-dlp + GUI + Hilfs-Pakete (~150 MB)...
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [FEHLER] pip install fehlgeschlagen.
    pause
    exit /b 1
)

REM ---- Playwright Chromium ---------------------------------------------
echo.
echo [4/5] Lade Chromium fuer den Browser-Login (~150 MB)...
"venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 (
    echo [WARN] Playwright Chromium-Install fehlgeschlagen.
    echo        Browser-Login wird nicht funktionieren.
    echo        Du kannst es spaeter per Hand starten:
    echo        venv\Scripts\python.exe -m playwright install chromium
)

REM ---- Deno (fuer YouTube n-sig) ---------------------------------------
echo.
echo [5/5] Lade Deno-Runtime fuer YouTube (~40 MB)...
if not exist runtime mkdir runtime
if not exist runtime\deno.exe (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$ProgressPreference='SilentlyContinue'; ^
         Invoke-WebRequest -Uri 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip' -OutFile 'deno.zip'; ^
         Expand-Archive -Path 'deno.zip' -DestinationPath 'runtime' -Force; ^
         Remove-Item 'deno.zip'"
    if exist runtime\deno.exe (
        echo Deno installiert.
    ) else (
        echo [WARN] Deno-Download fehlgeschlagen. YouTube-Downloads brauchen Deno.
        echo        Du kannst es spaeter manuell installieren:
        echo        https://docs.deno.com/runtime/getting_started/installation/
    )
) else (
    echo Deno bereits da - skip.
)

echo.
echo ===============================================
echo Installation FERTIG!
echo ===============================================
echo.
echo Starte mit:  2_START.cmd
echo.
pause
