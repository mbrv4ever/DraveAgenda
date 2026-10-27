@echo off
title DraveAgenda - EXE bouwen
cd /d "%~dp0"
set "VPY=%~dp0.venv\Scripts\python.exe"
if not exist "%VPY%" (
  echo Nieuwe .venv maken met Python 3.13...
  py -3.13 -m venv .venv || goto mislukt
)
"%VPY%" -m pip install -q --upgrade pip
"%VPY%" -m pip install -q -r requirements.txt pyinstaller pillow || goto mislukt
"%VPY%" make_icon.py
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --onedir --name DraveAgenda --icon assets\icon.ico --add-data "assets;assets" --add-data "DraveAgenda-Snelgids.pdf;." --collect-all neuvoice --collect-all onnxruntime --collect-all sounddevice --hidden-import stem --hidden-import model --hidden-import agenda_sync --hidden-import drave_update --exclude-module tkinter --exclude-module PyQt6.QtWebEngineCore --exclude-module PyQt6.QtWebEngineWidgets --exclude-module PyQt6.QtQml --exclude-module PyQt6.QtQuick --exclude-module matplotlib --exclude-module PIL draveagenda.py
if errorlevel 1 goto mislukt
if not exist "dist\DraveAgenda\DraveAgenda.exe" goto mislukt
xcopy /e /i /y assets "dist\DraveAgenda\assets" >nul
copy /y DraveAgenda-Snelgids.pdf "dist\DraveAgenda\" >nul
echo.
echo KLAAR: dist\DraveAgenda\DraveAgenda.exe
exit /b 0
:mislukt
echo MISLUKT - kijk hierboven voor de fout.
exit /b 1
