@echo off
setlocal
set "YSUNET_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%YSUNET_PYTHON%" set "YSUNET_PYTHON=%~dp0.runtime\python.exe"
"%YSUNET_PYTHON%" -m ysu_net_login.ruijie_cli %*
exit /b %errorlevel%
