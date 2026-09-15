@echo off
title Stellarium Desktop - Live Dev Console
cd /d "D:\10_Projects\Project_Stella\stellarium\apps\desktop"

set STELLA_HOME=C:\Users\Ilunaa\AppData\Local\stella
set HERMES_DESKTOP_DEV_SERVER=http://127.0.0.1:5174

echo ===================================================
echo   ✦ STELLARIUM SOVEREIGN STUDIO - LIVE DEV ✦
echo ===================================================
echo [1/3] Bundling Electron Main Process...
node scripts/bundle-electron-main.mjs --dev
node scripts/stage-native-deps.mjs

echo [2/3] Ensuring Vite Live Dev Server is running on port 5174...
start "Stellarium Vite HMR" /min cmd /c "npx vite --host 127.0.0.1 --port 5174"

echo [3/3] Launching Stellarium Desktop with Live Hot-Reload...
call npx wait-on http://127.0.0.1:5174
call npx electron .

echo Stellarium session closed.
pause
