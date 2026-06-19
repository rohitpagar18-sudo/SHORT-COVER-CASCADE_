@echo off
call venv\Scripts\activate.bat
echo Running shadow stop-loss lab (read-only, writes logs\shadow_sl.jsonl only)...
python scripts\update_shadow_sl.py
echo.
pause
