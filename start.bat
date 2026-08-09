@echo off
chcp 65001 >nul
echo ============================================
echo   Quantiva ?????????
echo ============================================
set PYTHONIOENCODING=utf-8
python scripts\webui.py --no-open
pause
