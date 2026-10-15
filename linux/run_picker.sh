#!/usr/bin/env bash
# Start everything a lecture needs on Linux: the student picker, and the
# controller remote that turns D-pad presses into the arrow keys your slides
# listen for. The scripts and their configs live in this linux/ folder; the
# roster and the themes are shared at the repo root.
#
#   linux/mini_picker.py       + linux/mini_config.json   the picker
#   linux/controller_remote.py + linux/config.json        the slide remote
#
# Run "uv sync" once at the repo root first so .venv exists. The remote waits
# for the controller if it is off, and reconnects if it drops. Extra arguments
# are passed to the picker.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
PY="$ROOT/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
  echo '.venv not found - run "uv sync" in the repo root first.' >&2
  exit 1
fi

# A remote left over from an earlier launch would send a second arrow key for
# every D-pad press, so clear one out before starting a new one.
pkill -f "$HERE/controller_remote.py" 2>/dev/null || true

# Detach the picker from this shell so closing the terminal does not close it.
setsid "$PY" "$HERE/mini_picker.py" "$@" >/dev/null 2>&1 < /dev/null &

if [[ ! -f "$HERE/controller_remote.py" ]]; then
  echo "Note: controller_remote.py not found - started the picker only."
  exit 0
fi

# The remote stays in the foreground: this terminal is where it reports things
# like "Controller disconnected", and Ctrl+C here stops it.
exec "$PY" "$HERE/controller_remote.py"
