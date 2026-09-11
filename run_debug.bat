@echo off
cd /d "%~dp0"
py ember_admin_winscp.py
if %errorlevel% neq 0 (
  echo.
  echo L'application s'est fermee avec une erreur.
  pause
)
