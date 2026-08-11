@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup_once.ps1"
if errorlevel 1 (
  echo.
  echo Setup did not finish. Review the error above, then run SETUP_ONCE.bat again.
  pause
  exit /b 1
)
echo.
echo Creator Intelligence Setup Once is complete.
pause
