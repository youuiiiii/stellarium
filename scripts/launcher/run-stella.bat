@echo off
setlocal
title Stella Desktop
set "REPO_ROOT=%~dp0..\.."
cd /d "%REPO_ROOT%\apps\desktop" || exit /b 1
if not defined STELLA_HOME set "STELLA_HOME=%LOCALAPPDATA%\Stellarium"
echo Launching Stella Desktop via Electron runtime...
call npx electron .
