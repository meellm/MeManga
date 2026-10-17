@echo off
REM MeManga launcher for Windows
REM Runs in the caller's working directory, so relative paths
REM (e.g. "import backup.json") resolve where the command was typed.

setlocal

for %%I in ("%~dp0..\..") do set "PROJECT_DIR=%%~fI"
set "PYTHON=%PROJECT_DIR%\venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Error: Virtual environment not found.
    echo Please run: python setup.py
    echo         or: scripts\windows\setup.bat
    exit /b 1
)

REM Not "-m memanga": that would search the caller's folder for modules.
REM -I keeps it (and PYTHONPATH) out until the launcher has filtered them.
"%PYTHON%" -I "%PROJECT_DIR%\scripts\memanga_launcher.py" %*
