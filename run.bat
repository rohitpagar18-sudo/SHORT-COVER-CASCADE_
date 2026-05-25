@echo off
if not exist venv\Scripts\activate.bat (
  python -m venv venv
  call venv\Scripts\activate.bat
  pip install -r requirements.txt
) else (
  call venv\Scripts\activate.bat
)
python -m src.main



