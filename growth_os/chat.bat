@echo off
rem Growth OS assistant - chat with the local LLM that manages your kanban.
cd /d "%~dp0"
set PYTHONPATH=.
.venv\Scripts\python.exe -m growthos.assistant %*
