@echo off
rem 从 office 目录启动 xAgent，这样项目根才是 office
rem 技能才会被扫到 <项目根>/office\.agents\skills\
cd /d <项目根>/office
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
echo Starting xAgent from <项目根>/office ...
echo.
python <项目根>/Agent/xAgent\main.py
echo.
echo Exited.
pause
