@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 bootstrap.py --install-experiments
) else (
  python bootstrap.py --install-experiments
)
pause
