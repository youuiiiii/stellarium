@echo off
setlocal
title Stella Desktop - Live Dev Console

set "REPO_ROOT=%~dp0..\.."
cd /d "%REPO_ROOT%\apps\desktop" || exit /b 1

if not defined STELLA_HOME set "STELLA_HOME=%LOCALAPPDATA%\Stellarium"
set "HERMES_DESKTOP_DEV_SERVER=http://127.0.0.1:5174"

echo ===================================================
echo   ✦ STELLA - LIVE DEVELOPMENT ✦
echo ===================================================
echo [1/3] Bundling Electron Main Process...
node scripts/bundle-electron-main.mjs --dev
node scripts/stage-native-deps.mjs

echo [2/3] Ensuring Vite Live Dev Server is running on port 5174...
start "Stella Vite HMR" /min cmd /c "npx vite --host 127.0.0.1 --port 5174"

echo [3/3] Launching Stella Desktop with Live Hot-Reload...
call npx wait-on http://127.0.0.1:5174
call npx electron .

echo Stella session closed.
pause
