@echo off
cd /d "%~dp0\.."
python app.py --data-dir "%CD%\.performance-data\interactive.sqlite3" --performance-test-db