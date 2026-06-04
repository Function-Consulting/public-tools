@echo off
cd /d "%~dp0"
python ocr_pdf.py %*
pause
