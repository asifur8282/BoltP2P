@echo off
setlocal
cd /d "%~dp0"
echo ====================================================================
echo  JiffBoltP2P Desktop Daemon - Windows 11 Executable Packaging
echo ====================================================================
echo.
taskkill /F /IM JiffBoltP2P.exe >nul 2>&1
taskkill /F /IM BoltP2P.exe >nul 2>&1
python build_exe.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Build failed! Check terminal output above.
    exit /b %ERRORLEVEL%
)

echo.
echo Build complete. Executable ready at dist\JiffBoltP2P.exe
endlocal
