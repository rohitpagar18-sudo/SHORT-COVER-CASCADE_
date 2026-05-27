@echo off
call venv\Scripts\activate.bat
echo Updating dashboard + Parquet...
python scripts\update_dashboard.py
echo Bot auto-syncs at 15:35 IST daily. update_dashboard.bat is only for manual mid-day refresh if you want to peek before 15:35.
echo.
pause
