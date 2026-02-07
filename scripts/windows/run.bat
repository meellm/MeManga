@echo off
REM MeManga launcher for Windows

cd /d "%~dp0..\.."

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe -m memanga %*
) else (
    echo Error: Virtual environment not found.
    echo Please run: python setup.py
    echo         or: scripts\windows\setup.bat
    exit /b 1
)
