@echo off
REM Builds dist\TaskTrail\TaskTrail.exe (one folder, single process, no console window) with PyInstaller.
REM Run this on Windows from the folder containing tasktrail.py.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onedir --windowed --name TaskTrail --icon icon.ico ^
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml --exclude-module PySide6.QtMultimedia ^
  --exclude-module PySide6.QtCharts --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtDataVisualization ^
  --exclude-module PySide6.QtPdf --exclude-module PySide6.QtLocation ^
  tasktrail.py
echo.
echo Done: dist\TaskTrail\TaskTrail.exe
echo To build the installer, install NSIS and run:  makensis installer.nsi
pause
