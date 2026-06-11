@echo off
REM ============================================================
REM  Short Cover Cascade — Frontend launcher
REM  - Independent of run.bat (the bot launcher).
REM  - Ensures Python API deps are installed.
REM  - Builds the React app once (if dist is missing).
REM  - Launches uvicorn serving BOTH /api and the static SPA
REM    on a single port (default 8000).
REM ============================================================

setlocal
cd /d "%~dp0"

REM ---- resolve project root (parent of this folder) ----
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "VENV_PY=%PROJECT_ROOT%\venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
  echo [run_ui] ERROR: Python venv not found at %VENV_PY%
  echo [run_ui] Run the bot's setup first (creates venv/), then retry.
  exit /b 1
)

REM ---- ensure API deps are installed ----
echo [run_ui] Verifying Python API deps...
"%VENV_PY%" -c "import fastapi, uvicorn, ruamel.yaml, pydantic" 2>nul
if errorlevel 1 (
  echo [run_ui] Installing FastAPI + Uvicorn + ruamel.yaml + Pydantic into venv...
  "%VENV_PY%" -m pip install --quiet fastapi "uvicorn[standard]" "ruamel.yaml" pydantic
  if errorlevel 1 (
    echo [run_ui] pip install FAILED. Aborting.
    exit /b 1
  )
)

REM ---- build the SPA if dist is missing ----
if not exist "%~dp0web\dist\index.html" (
  echo [run_ui] frontend\web\dist\ missing — building SPA...
  where npm >nul 2>&1
  if errorlevel 1 (
    echo.
    echo [run_ui] ERROR: 'npm' not found on PATH.
    echo [run_ui] Install Node.js LTS from https://nodejs.org and re-run.
    echo [run_ui] Alternatively, for development run: cd frontend\web ^&^& npm install ^&^& npm run dev
    echo [run_ui]   then run this script in another window to start the API on port 8000.
    exit /b 1
  )
  pushd "%~dp0web"
  if not exist "node_modules" (
    echo [run_ui] Installing JS deps (first run, may take a minute)...
    call npm install
    if errorlevel 1 (
      popd
      echo [run_ui] npm install FAILED. Aborting.
      exit /b 1
    )
  )
  echo [run_ui] Building production bundle...
  call npm run build
  if errorlevel 1 (
    popd
    echo [run_ui] npm run build FAILED. Aborting.
    exit /b 1
  )
  popd
)

REM ---- launch the API + SPA on a single port ----
set "SCC_UI_PORT=8000"
if not "%~1"=="" set "SCC_UI_PORT=%~1"

echo.
echo [run_ui] Serving UI at http://localhost:%SCC_UI_PORT%/
echo [run_ui] API root        http://localhost:%SCC_UI_PORT%/api/health
echo [run_ui] Press Ctrl+C to stop.
echo.

pushd "%~dp0api"
"%VENV_PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %SCC_UI_PORT%
popd

endlocal
