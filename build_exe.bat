@echo off
setlocal
cd /d "%~dp0"

title Azeroth Eras Control - Build EXE
echo ==========================================
echo   AZEROTH ERAS CONTROL - BUILD EXE
echo ==========================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
) else (
    where python >nul 2>nul
    if %errorlevel% neq 0 (
        echo [ERREUR] Python est introuvable.
        echo Installe Python 3 puis coche "Add Python to PATH".
        goto :fail
    )
)

echo [1/4] Python detecte :
%PY% --version
echo.

echo [2/4] Installation / mise a jour des dependances...
%PY% -m pip install --upgrade pip
if %errorlevel% neq 0 goto :fail
%PY% -m pip install -r requirements.txt pyinstaller
if %errorlevel% neq 0 goto :fail

echo.
echo [3/4] Nettoyage ancien build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist AzerothErasControl.spec del /f /q AzerothErasControl.spec
if exist AzerothErasControl.exe del /f /q AzerothErasControl.exe

echo.
echo [4/4] Creation de AzerothErasControl.exe...
%PY% -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name AzerothErasControl ^
  --icon "wow_icon.ico" ^
  --add-data "wow_icon.ico;." ^
  --add-data "setup.sh;." ^
  --add-data "finalize.sh;." ^
  --collect-all customtkinter ^
  --collect-all cryptography ^
  --hidden-import ember_admin ^
  --hidden-import ember_admin_core ^
  --hidden-import ember_admin_files ^
  ember_admin_winscp.py

if %errorlevel% neq 0 goto :fail

if not exist "dist\AzerothErasControl.exe" (
    echo.
    echo [ERREUR] PyInstaller a termine mais l'EXE est introuvable.
    goto :fail
)

move /Y "dist\AzerothErasControl.exe" "%CD%\AzerothErasControl.exe" >nul
if %errorlevel% neq 0 goto :fail

echo.
echo Nettoyage total : conservation de l'EXE uniquement...

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__
if exist AzerothErasControl.spec del /f /q AzerothErasControl.spec

for %%F in (*) do (
    if /I not "%%~nxF"=="AzerothErasControl.exe" (
        if /I not "%%~nxF"=="build_exe.bat" (
            del /f /q "%%~fF" >nul 2>nul
        )
    )
)

for /D %%D in (*) do (
    rmdir /s /q "%%~fD" >nul 2>nul
)

echo.
echo ==========================================
echo   BUILD TERMINE AVEC SUCCES
echo ==========================================
echo.
echo EXE :
echo   %CD%\AzerothErasControl.exe
echo.
echo Le dossier ne contient plus que l'EXE et ce script de build.
echo Tu peux supprimer build_exe.bat apres fermeture de cette fenetre si tu veux.
echo.
pause
exit /b 0

:fail
echo.
echo ==========================================
echo   ECHEC DU BUILD
echo ==========================================
echo.
echo Aucun nettoyage destructif des sources n'a ete effectue.
pause
exit /b 1
