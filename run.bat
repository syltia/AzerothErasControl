@echo off
cd /d "%~dp0"

py -c "import customtkinter, paramiko, windnd" >nul 2>&1
if errorlevel 1 (
    echo Installation des dependances...
    py -m pip install -r requirements.txt
)

start "" pyw ember_admin_winscp_pro.py
exit
