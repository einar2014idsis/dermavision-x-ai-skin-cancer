@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" interfaz.py --seguimiento
if errorlevel 1 pause
