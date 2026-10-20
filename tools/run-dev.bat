@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\pythonw.exe" (
  echo Python environment missing. See docs/development.md.
  pause
  exit /b 2
)
rem Source execution uses the regular settings profile and single-instance guard.
rem Close the existing CamFloat first to run the edited source.
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "VLC_HOME=%CD%\vendor\vlc"
start "" ".venv\Scripts\pythonw.exe" -B -m camfloat
