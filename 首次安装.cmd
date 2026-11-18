@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 bootstrap.py --setup
) else (
  python bootstrap.py --setup
)
pause
