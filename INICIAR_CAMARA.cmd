@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" interfaz.py --individual
if errorlevel 1 pause
