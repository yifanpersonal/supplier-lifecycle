@echo off
cd /d "%~dp0"
python -m backend.server --port 8080
pause
