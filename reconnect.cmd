@echo off
setlocal
set "YSUNET_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%YSUNET_PYTHON%" set "YSUNET_PYTHON=%~dp0.runtime\python.exe"
if not exist "%YSUNET_PYTHON%" (
  echo Please run Setup.cmd first.
  pause
  exit /b 1
)
"%YSUNET_PYTHON%" "%~dp0reconnect.py"  %*
set "YSUNET_RESULT=%errorlevel%"
pause
exit /b %YSUNET_RESULT%
