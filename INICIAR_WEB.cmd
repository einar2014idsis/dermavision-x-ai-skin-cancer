@echo off
cd /d "%~dp0"
if not exist "web\dist\index.html" (
    pushd web
    call npm.cmd run build
    if errorlevel 1 (
        popd
        exit /b 1
    )
    popd
)
echo Abre http://127.0.0.1:8765/
".venv\Scripts\python.exe" -m uvicorn web_api:app --host 127.0.0.1 --port 8765
if errorlevel 1 pause
