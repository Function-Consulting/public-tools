@echo off
setlocal
cd /d "%~dp0"
python pdf_to_csv.py
if errorlevel 1 pause
