@echo off
title Rate Change Assurance Workbench
echo ========================================================
echo   Starting Rate Change Assurance Workbench Server...
echo ========================================================
echo.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Error: Python virtual environment not found in .venv.
    echo Please make sure the .venv folder exists.
    pause
    exit /b 1
)

echo Opening browser at http://127.0.0.1:8000 ...
start http://127.0.0.1:8000

echo Starting backend Uvicorn server on http://127.0.0.1:8000 ...
echo Press CTRL+C at any time to stop the server.
echo.
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
pause
