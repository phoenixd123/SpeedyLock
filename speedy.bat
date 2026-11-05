@echo off
rem SpeedyLock launcher. Finds a Python 3 interpreter and forwards arguments.
setlocal
set "HERE=%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%HERE%speedy.py" %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python "%HERE%speedy.py" %*
  exit /b %ERRORLEVEL%
)

echo SpeedyLock needs Python 3.8 or newer.
echo Install it from https://www.python.org/downloads/ and tick
echo "Add python.exe to PATH" during setup, then run this file again.
pause
exit /b 1
