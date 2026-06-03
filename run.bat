@echo off
REM Short Cover Cascade — Phase 5 live launcher.
REM Activates .venv (creates it if missing), prints a status banner,
REM then runs python -m src.main.
REM
REM Bot runs continuously until market close (15:30 IST) or Ctrl+C.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    if exist "venv\Scripts\activate.bat" (
        call "venv\Scripts\activate.bat"
    ) else (
        echo [run.bat] Creating virtualenv in .venv ...
        python -m venv .venv || goto :fail
        call ".venv\Scripts\activate.bat"
        echo [run.bat] Installing requirements ...
        python -m pip install --upgrade pip
        pip install -r requirements.txt || goto :fail
    )
) else (
    call ".venv\Scripts\activate.bat"
)

REM ---- Pre-flight banner --------------------------------------------------
echo.
echo ============================================================
echo   SHORT COVER CASCADE - Phase 5 (ALERT-ONLY)
echo ============================================================
echo   WARNING: Bot will run continuously until market close
echo            (15:30 IST) or until you press Ctrl+C.
echo.

REM Active broker (lifted from config.yaml).
for /f "tokens=2 delims=:" %%a in (
  'findstr /b /c:"  active_feed:" config\config.yaml'
) do (
  set ACTIVE_FEED=%%a
)
if defined ACTIVE_FEED (
    for /f "tokens=1" %%b in ("%ACTIVE_FEED%") do set ACTIVE_FEED=%%b
    echo   Active broker  : %ACTIVE_FEED%
) else (
    echo   Active broker  : ^(unknown - check config\config.yaml^)
)

REM Token date from secrets.env (Kite is most common).
for /f "tokens=2 delims==" %%a in (
  'findstr /b /c:"KITE_TOKEN_DATE=" config\secrets.env'
) do (
  set KITE_TOKEN_DATE=%%a
)
if defined KITE_TOKEN_DATE (
    echo   KITE_TOKEN_DATE: %KITE_TOKEN_DATE%
) else (
    echo   KITE_TOKEN_DATE: ^(not set^)
)
for /f "tokens=2 delims==" %%a in (
  'findstr /b /c:"UPSTOX_TOKEN_DATE=" config\secrets.env'
) do (
  set UPSTOX_TOKEN_DATE=%%a
)
if defined UPSTOX_TOKEN_DATE (
    echo   UPSTOX_TOKEN_DATE: %UPSTOX_TOKEN_DATE%
) else (
    echo   UPSTOX_TOKEN_DATE: ^(not set^)
)
echo ============================================================
echo.

REM Disable AC standby while the bot runs. If the laptop sleeps during
REM a long internet outage, the bot's reconnect loop never gets to
REM resume and we miss every 5-min candle until someone wakes it.
REM Restored to 30 min after the bot exits so normal power policy
REM resumes for the user.
powercfg /change standby-timeout-ac 0

python -m src.main
set EXITCODE=%ERRORLEVEL%

powercfg /change standby-timeout-ac 30

endlocal & exit /b %EXITCODE%

:fail
echo [run.bat] Setup failed.
endlocal & exit /b 1
