@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  call SETUP.cmd
  if errorlevel 1 exit /b 1
)
.venv\Scripts\python.exe my-harness-ui\server.py --port 8003
pause
