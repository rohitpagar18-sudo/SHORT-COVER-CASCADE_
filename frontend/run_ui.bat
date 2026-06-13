@echo off
REM ============================================================
REM  Short Cover Cascade — Frontend launcher
REM  Uses goto-based flow (no nested if blocks) for CMD compat.
REM ============================================================
setlocal
cd /d "%~dp0"

REM ---- resolve project root (parent of frontend\) ----
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "VENV_PY=%PROJECT_ROOT%\venv\Scripts\python.exe"

echo [run_ui] Project root: %PROJECT_ROOT%
echo [run_ui] Python venv:  %VENV_PY%

if not exist "%VENV_PY%" goto :no_venv

REM ---- ensure API deps are installed ----
echo [run_ui] Checking Python API deps...
"%VENV_PY%" -c "import fastapi, uvicorn, ruamel, pydantic" 2>nul
if errorlevel 1 goto :install_py_deps
goto :check_spa

:install_py_deps
echo [run_ui] Installing Python deps from frontend\requirements.txt...
"%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto :pip_fail

:check_spa
if exist "%~dp0web\dist\index.html" goto :launch

REM ---- build the SPA (first run only) ----
echo [run_ui] web\dist not found. Need to build the React app first.
where npm >nul 2>nul
if errorlevel 1 goto :no_npm

cd "%~dp0web"

if not exist "node_modules" goto :npm_install
goto :npm_build

:npm_install
echo [run_ui] Running npm install (first run, takes 1-2 min)...
call npm install
if errorlevel 1 goto :npm_fail

:npm_build
echo [run_ui] Building production bundle...
call npm run build
if errorlevel 1 goto :build_fail
cd "%~dp0"

:launch
set "SCC_UI_PORT=8000"
if not "%~1"=="" set "SCC_UI_PORT=%~1"

echo.
echo ============================================================
echo  UI ready:  http://localhost:%SCC_UI_PORT%/
echo  API:       http://localhost:%SCC_UI_PORT%/api/health
echo  Press Ctrl+C to stop.
echo ============================================================
echo.

cd "%~dp0api"
"%VENV_PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %SCC_UI_PORT%
goto :eof

:no_venv
echo.
echo ERROR: venv not found at:
echo   %VENV_PY%
echo Run the bot setup first so venv\ exists, then retry.
echo.
pause
exit /b 1

:pip_fail
echo.
echo ERROR: pip install failed. Check internet connection and retry.
echo.
pause
exit /b 1

:no_npm
echo.
echo ERROR: npm not found on PATH.
echo Install Node.js LTS from https://nodejs.org then re-run.
echo.
echo TIP: After installing Node, open a NEW Command Prompt and retry.
echo.
pause
exit /b 1

:npm_fail
echo.
echo ERROR: npm install failed.
echo.
pause
exit /b 1

:build_fail
echo.
echo ERROR: npm run build failed.
echo.
pause
exit /b 1
