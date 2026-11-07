@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" interfaz.py
if errorlevel 1 pause
