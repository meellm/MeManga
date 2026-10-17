@echo off
REM MeManga setup for Windows
REM Wrapper that calls the cross-platform Python setup
REM setup.py switches to the project root itself; the caller's
REM working directory is left unchanged.

setlocal

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Python not found. Please install Python 3.10+ from python.org
    exit /b 1
)

python "%~dp0..\..\setup.py"
