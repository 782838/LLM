@echo off
rem 从 office 目录启动 xAgent，这样项目根才是 office
rem 技能才会被扫到 D:\LLM\office\.agents\skills\
cd /d D:\LLM\office
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
echo Starting xAgent from D:\LLM\office ...
echo.
python D:\LLM\Agent\xAgent\main.py
echo.
echo Exited.
pause
