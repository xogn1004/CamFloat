@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. See docs/development.md.
  exit /b 2
)
".venv\Scripts\python.exe" -B tools/check.py %*
exit /b %errorlevel%
