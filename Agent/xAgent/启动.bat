@echo off
rem 切到脚本自己所在的目录，不写死绝对路径
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
echo Starting xAgent...
echo.
python main.py
echo.
echo Exited.
pause
