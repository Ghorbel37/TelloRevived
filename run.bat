@echo off
rem Start Tello Revived from source. Uses uv if installed, otherwise a plain venv.
cd /d "%~dp0"
where uv >nul 2>nul
if %errorlevel%==0 (
    uv run tello-revived %*
    exit /b
)
if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment... ^(installing uv makes this faster: https://docs.astral.sh/uv/^)
    python -m venv .venv || exit /b 1
    .venv\Scripts\python.exe -m pip install -e . || exit /b 1
)
.venv\Scripts\python.exe -m tello_revived %*
