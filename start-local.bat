@echo off
setlocal
set "ROOT=%~dp0"

start "Delta Backend" /min cmd.exe /k ""%ROOT%backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir "%ROOT%backend" --host 127.0.0.1 --port 8000"
start "Delta Frontend" /min cmd.exe /k "node "%ROOT%frontend\node_modules\vite\bin\vite.js" "%ROOT%frontend" --host 127.0.0.1"

timeout /t 3 /nobreak >nul
start "" msedge.exe http://127.0.0.1:5173/

endlocal
