@echo off
setlocal
cd /d "%~dp0"
python pdf_to_markdown.py
if errorlevel 1 pause
