@echo off
REM 启动后端（需先创建并激活虚拟环境、安装依赖，见 README）
cd /d %~dp0
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
