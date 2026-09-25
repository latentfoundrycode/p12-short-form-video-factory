@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "SFVF_EC=%ERRORLEVEL%"
echo.
echo (A full log was written to install_report.txt in this folder.)
pause
exit /b %SFVF_EC%
