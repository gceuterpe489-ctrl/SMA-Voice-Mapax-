@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\INSTALAR_OLLAMA.ps1"
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
