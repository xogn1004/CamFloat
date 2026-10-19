@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. See docs/development.md.
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -B -X utf8 tools/android_camera_app.py
set "check_exit=%errorlevel%"
pause
exit /b %check_exit%
