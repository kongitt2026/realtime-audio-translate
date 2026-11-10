@echo off
chcp 65001 >nul
title 实时音视频翻译模块
cd /d "%~dp0"
echo [启动] 实时音视频翻译模块 http://127.0.0.1:8790
start "" "http://127.0.0.1:8790"
".venv\Scripts\python.exe" server\main.py
pause
