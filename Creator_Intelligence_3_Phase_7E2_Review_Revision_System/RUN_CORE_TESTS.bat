@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run SETUP_ONCE.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate
python -m creator_intelligence.tests.test_database
python -m creator_intelligence.tests.test_config
pause
