@echo off
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish-update.ps1"
if errorlevel 1 (
    echo Update publishing failed. See the error above.
) else (
    echo Update published successfully.
)
pause
