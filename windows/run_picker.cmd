@echo off
rem Start everything a lecture needs on Windows: the student picker, and
rem the controller remote that turns D-pad presses into the arrow keys your
rem slides listen for. The scripts live in this windows\ folder; their configs,
rem the roster and the themes are shared and live at the repo root.
rem
rem   windows\mini_picker.py       + mini_config.json   the picker
rem   windows\controller_remote.py + config.json        the slide remote
rem
rem Run "uv sync" once at the repo root first so .venv exists. Make a desktop shortcut to this
rem file and both are one double-click away. Turn the controller on BEFORE
rem launching - the remote exits if it cannot find a pad at startup.
setlocal
set "HERE=%~dp0"
set "ROOT=%~dp0..\"

rem A remote left over from an earlier launch would send a second arrow key for
rem every D-pad press, so clear one out before starting a new one.
taskkill /FI "WINDOWTITLE eq Slide Remote*" /F >nul 2>&1

if not exist "%ROOT%.venv\Scripts\pythonw.exe" (
  echo .venv not found - run "uv sync" in the repo root first.
  pause
  exit /b 1
)

rem python.exe is a console program, so launching the picker with it leaves a
rem black terminal behind the picker for the whole lecture. pythonw.exe is the
rem same interpreter with no console attached.
start "" "%ROOT%.venv\Scripts\pythonw.exe" "%HERE%mini_picker.py" %*

rem The remote gets a console, minimized, on purpose: it has no window of its
rem own, so that console is both the only way to stop it (close the window) and
rem where it says things like "No controller detected".
if not exist "%HERE%controller_remote.py" (
  echo Note: controller_remote.py not found - started the picker only.
  exit /b 0
)
start "Slide Remote" /min "%ROOT%.venv\Scripts\python.exe" "%HERE%controller_remote.py"
