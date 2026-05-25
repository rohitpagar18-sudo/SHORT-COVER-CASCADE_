@echo off
if not exist venv\Scripts\activate.bat (
  python -m venv venv
  call venv\Scripts\activate.bat
  pip install -r requirements.txt
) else (
  call venv\Scripts\activate.bat
)
python -m src.main






#====================================OR ===========================


@echo off
REM Short Cover Cascade - Windows launcher.
REM Activates .venv (creates it if missing) and runs python -m src.main.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo [run.bat] Creating virtualenv in .venv ...
    python -m venv .venv || goto :fail
    call ".venv\Scripts\activate.bat"
    echo [run.bat] Installing requirements ...
    python -m pip install --upgrade pip
    pip install -r requirements.txt || goto :fail
) else (
    call ".venv\Scripts\activate.bat"
)

python -m src.main
set EXITCODE=%ERRORLEVEL%
endlocal & exit /b %EXITCODE%

:fail
echo [run.bat] Setup failed.
endlocal & exit /b 1

