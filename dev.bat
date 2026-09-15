@echo off
setlocal
title Stella Desktop - Dev Server
cd /d "%~dp0apps\desktop" || exit /b 1
if not defined STELLA_HOME set "STELLA_HOME=%LOCALAPPDATA%\Stellarium"

echo ===================================================
echo   ✦ STELLA - LIVE DEVELOPMENT ✦
echo ===================================================
call npm run dev
