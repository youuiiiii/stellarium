@echo off
setlocal
title Stellarium Desktop - Dev Server
cd /d "%~dp0apps\desktop"

echo ===================================================
echo   ✦ STELLARIUM SOVEREIGN STUDIO - LIVE DEV ✦
echo ===================================================
call npm run dev
