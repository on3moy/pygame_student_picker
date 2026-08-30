@echo off
rem Launch the picker WITHOUT a console window.
rem
rem "uv run mini_picker.py" works fine, but python.exe is a console program, so
rem Windows opens a black terminal alongside the picker and keeps it there for
rem the whole lecture. pythonw.exe is the same interpreter with no console
rem attached, so this launcher starts the picker on its own.
rem
rem Run "uv sync" once first so .venv exists. Make a desktop shortcut to this
rem file and the picker is one double-click away.
setlocal
set "HERE=%~dp0"
if exist "%HERE%.venv\Scripts\pythonw.exe" (
  start "" "%HERE%.venv\Scripts\pythonw.exe" "%HERE%mini_picker.py" %*
) else (
  echo .venv not found - run "uv sync" in this folder first.
  pause
)
