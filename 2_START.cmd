@echo off
REM TEE yt-dlp Downloader - Launcher.

cd /d "%~dp0"

if not exist "venv\Scripts\pythonw.exe" (
    echo [FEHLER] Es scheint die Installation fehlt.
    echo Bitte zuerst 1_INSTALL.cmd ausfuehren.
    echo.
    pause
    exit /b 1
)

REM Add Deno to PATH so yt-dlp finds it
if exist "%~dp0runtime\deno.exe" (
    set "PATH=%~dp0runtime;%PATH%"
)

REM pythonw.exe = ohne Konsolen-Fenster
start "" "venv\Scripts\pythonw.exe" -X utf8 -m app.yt_dlp_gui
