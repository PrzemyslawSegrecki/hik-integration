@echo off
rem Builds the Windows installers (MSI + NSIS). Requires Rust and Node.js.
cd /d "%~dp0"

where cargo >nul 2>nul || (echo Rust is not installed - get it from https://rustup.rs & exit /b 1)
where npx >nul 2>nul || (echo Node.js is not installed - get it from https://nodejs.org & exit /b 1)

call npx --yes @tauri-apps/cli@1 build || exit /b 1

echo.
echo Installers:
dir /b src-tauri\target\release\bundle\msi\*.msi src-tauri\target\release\bundle\nsis\*.exe
