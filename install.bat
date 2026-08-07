@echo off
title Commerce Manager - Installation
cd /d "%~dp0"

echo ============================================
echo   Commerce Manager - Installation
echo ============================================
echo.
echo Installation des dependances Python...
echo.

pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERREUR: Python ou pip n'est pas installe ou introuvable.
    echo Installez Python depuis https://www.python.org/downloads/
    echo IMPORTANT: cochez "Add Python to PATH" pendant l'installation.
    pause
    exit /b 1
)

echo.
echo Preparation de la base de donnees...
python database\seed.py

echo.
echo ============================================
echo   Installation terminee !
echo   Double-cliquez sur run.bat pour demarrer.
echo ============================================
pause
