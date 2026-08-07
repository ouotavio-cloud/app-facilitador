@echo off
REM Abre o App Facilitador com duplo clique, sem precisar do terminal.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python app.py
pause
