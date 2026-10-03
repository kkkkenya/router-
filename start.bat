@echo off
cd /d "%~dp0"
python -m routerdash %*
if errorlevel 1 pause
