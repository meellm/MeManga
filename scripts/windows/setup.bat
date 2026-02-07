@echo off
REM MeManga setup for Windows
REM Wrapper that calls the cross-platform Python setup

cd /d "%~dp0..\.."

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Python not found. Please install Python 3.10+ from python.org
    exit /b 1
)

python setup.py
