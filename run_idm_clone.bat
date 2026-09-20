@echo off
REM Launcher untuk IDM Clone -- %~dp0 otomatis berisi path folder file .bat
REM ini sendiri, jadi shortcut tetap jalan walau project dipindah folder.
cd /d "%~dp0"
python gui_main.py
