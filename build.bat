@echo off
setlocal
cd /d "%~dp0"
set "CAMFLOAT_STAGE=%LOCALAPPDATA%\CamFloatBuild\current"

if not exist ".venv\Scripts\python.exe" (
  py -3.14 -m venv .venv
)

call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

call ".venv\Scripts\python.exe" make_icon.py
if errorlevel 1 goto :failed

call ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean ^
  --distpath "%CAMFLOAT_STAGE%\dist" --workpath "%CAMFLOAT_STAGE%\work" CamFloat.spec
if errorlevel 1 goto :failed

robocopy "%CAMFLOAT_STAGE%\dist\CamFloat" "%~dp0release\CamFloat" /E /COPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS
if errorlevel 8 goto :failed
copy /y README.md "%~dp0release\CamFloat\README.md" >nul
copy /y CHANGELOG.md "%~dp0release\CamFloat\CHANGELOG.md" >nul
copy /y THIRD_PARTY.md "%~dp0release\CamFloat\THIRD_PARTY.md" >nul
if exist "%~dp0release\CamFloat\QA-summary.json" del /q "%~dp0release\CamFloat\QA-summary.json"
robocopy "%~dp0licenses" "%~dp0release\CamFloat\licenses" /E /COPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS
if errorlevel 8 goto :failed

echo.
echo Build complete: release\CamFloat\CamFloat.exe
echo VLC media player must be installed on the PC that runs CamFloat.
exit /b 0

:failed
echo.
echo Build failed. Check the error output above.
exit /b 1
