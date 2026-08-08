@echo off
setlocal enabledelayedexpansion
title BRecorder - Installer
color 0A
cls

echo.
echo ========================================
echo     BRecorder v1.0 - Installation
echo ========================================
echo.

:: Get script directory
set "APP_DIR=%~dp0"
set "INSTALL_DIR=%LOCALAPPDATA%\BRecorder"

:: Find EXE - look for both possible names
set "EXE_NAME="
if exist "%APP_DIR%B Recorder.exe" set "EXE_NAME=B Recorder.exe"
if exist "%APP_DIR%BRecorder.exe" set "EXE_NAME=BRecorder.exe"
if "%EXE_NAME%"=="" (
    for %%f in ("%APP_DIR%*.exe") do set "EXE_NAME=%%~nxf"
)

if "%EXE_NAME%"=="" (
    echo ERROR: No EXE found in %APP_DIR%
    echo Please make sure BRecorder.exe is in this folder
    pause
    exit /b 1
)

echo Found: %EXE_NAME%
echo Target: %INSTALL_DIR%
echo.

:: Remove old installation
if exist "%INSTALL_DIR%" (
    echo [1/6] Removing old version...
    rmdir /s /q "%INSTALL_DIR%" 2>nul
)

:: Create install directory
mkdir "%INSTALL_DIR%" 2>nul
echo [2/6] Created install folder

:: Copy main EXE with error checking
echo [3/6] Copying EXE...
set "SRC_EXE=%APP_DIR%%EXE_NAME%"
set "DST_EXE=%INSTALL_DIR%\%EXE_NAME%"
copy "%SRC_EXE%" "%DST_EXE%" /Y >nul
if errorlevel 1 (
    echo ERROR: Copy failed!
    echo Source: %SRC_EXE%
    echo Target: %DST_EXE%
    pause
    exit /b 1
)
echo OK

:: Copy assets (check multiple possible locations)
set "ASSETS_OK=0"
if exist "%APP_DIR%BRecorder\assets\" (
    echo [4/6] Copying BRecorder/assets...
    xcopy "%APP_DIR%BRecorder\assets" "%INSTALL_DIR%\BRecorder\assets\" /E /I /Y /Q >nul 2>&1
    set "ASSETS_OK=1"
)
if exist "%APP_DIR%assets\" (
    echo [4/6] Copying assets...
    xcopy "%APP_DIR%assets" "%INSTALL_DIR%\BRecorder\assets\" /E /I /Y /Q >nul 2>&1
    set "ASSETS_OK=1"
)
if !ASSETS_OK!==1 (echo Assets copied) else (echo No assets folder found)

:: Copy bin (ffmpeg, ffprobe)
set "BIN_OK=0"
if exist "%APP_DIR%BRecorder\bin\" (
    echo [5/6] Copying BRecorder/bin...
    xcopy "%APP_DIR%BRecorder\bin" "%INSTALL_DIR%\BRecorder\bin\" /E /I /Y /Q >nul 2>&1
    set "BIN_OK=1"
)
if exist "%APP_DIR%bin\" (
    echo [5/6] Copying bin...
    xcopy "%APP_DIR%bin" "%INSTALL_DIR%\BRecorder\bin\" /E /I /Y /Q >nul 2>&1
    set "BIN_OK=1"
)
if !BIN_OK!==1 (echo Binaries copied) else (echo No bin folder found)

:: Create shortcuts with proper icon extraction
echo [6/6] Creating shortcuts...

:: Desktop shortcut
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
"$WScriptShell = New-Object -ComObject WScript.Shell; ^
$Shortcut = $WScriptShell.CreateShortcut(\"$env:USERPROFILE\\Desktop\\BRecorder.lnk\"); ^
$Shortcut.TargetPath = \"%INSTALL_DIR%\\%EXE_NAME%\"; ^
$Shortcut.WorkingDirectory = \"%INSTALL_DIR%\"; ^
$Shortcut.IconLocation = \"%INSTALL_DIR%\\%EXE_NAME%,0\"; ^
$Shortcut.Save(); ^
Write-Host \"Desktop shortcut created\";"

:: Start Menu shortcut
set "START_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\BRecorder"
if not exist "%START_MENU%" mkdir "%START_MENU%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
"$WScriptShell = New-Object -ComObject WScript.Shell; ^
$Shortcut = $WScriptShell.CreateShortcut(\"%START_MENU%\\BRecorder.lnk\"); ^
$Shortcut.TargetPath = \"%INSTALL_DIR%\\%EXE_NAME%\"; ^
$Shortcut.WorkingDirectory = \"%INSTALL_DIR%\"; ^
$Shortcut.IconLocation = \"%INSTALL_DIR%\\%EXE_NAME%,0\"; ^
$Shortcut.Save(); ^
Write-Host \"Start Menu shortcut created\";"

:: Pin to Start Menu (optional)
echo.
echo Would you like to pin BRecorder to Start Menu? (Y/N)
choice /c YN /n /m "Pin to Start Menu? "
if errorlevel 2 goto :skip_pin
powershell -Command ^
"$shell = New-Object -ComObject Shell.Application; ^
$folder = $shell.Namespace('%START_MENU%'); ^
$item = $folder.ParseName('BRecorder.lnk'); ^
$item.InvokeVerb('pintostart'); ^
Write-Host 'Pinned to Start Menu';"
:skip_pin

:: Add to PATH for Win+R access
echo.
echo Would you like to add BRecorder to PATH (for Win+R access)? (Y/N)
choice /c YN /n /m "Add to PATH? "
if errorlevel 2 goto :skip_path

:: Add to user PATH
powershell -Command ^
"$path = [Environment]::GetEnvironmentVariable('Path', 'User'); ^
$newPath = '%INSTALL_DIR%;' + $path; ^
[Environment]::SetEnvironmentVariable('Path', $newPath, 'User'); ^
Write-Host 'Added to PATH. Restart for changes to take effect.';"
:skip_path

echo.
echo ========================================
echo        ✅ Installation Complete!
echo ========================================
echo 📁 Location: %INSTALL_DIR%
echo 🖥️  Desktop shortcut created
echo 🔍 Start Menu: BRecorder folder
echo ⌨️  Win+R: Type "BRecorder" (if added to PATH)
echo.
echo Press any key to launch...
pause >nul

start "" "%INSTALL_DIR%\%EXE_NAME%"