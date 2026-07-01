#!/usr/bin/env bash
# Quickstart: set up once, then launch the Manaless web builder.
#
#   ./run.sh                 # start on http://127.0.0.1:8000
#   PORT=9000 ./run.sh       # pick a port
#   ./run.sh --reload        # extra args pass through to `python -m manaless.web`
#
# First run creates .venv and installs the package (editable) + web extras.
# Works on Linux/macOS and in Git Bash on Windows.
set -euo pipefail
cd "$(dirname "$0")"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

# 1. Virtual environment -----------------------------------------------------
pick_py() {
  if [ -x ".venv/Scripts/python.exe" ]; then echo ".venv/Scripts/python.exe"   # Windows layout
  elif [ -x ".venv/bin/python" ]; then echo ".venv/bin/python"                  # POSIX layout
  else echo ""; fi
}
PY="$(pick_py)"
if [ -z "$PY" ]; then
  echo "Creating virtual environment (.venv)..."
  python3 -m venv .venv 2>/dev/null || python -m venv .venv
  PY="$(pick_py)"
fi

# 2. Dependencies ------------------------------------------------------------
if ! "$PY" -c "import manaless, uvicorn, fastapi, jinja2, multipart" 2>/dev/null; then
  echo "Installing dependencies (editable + [web] extra)..."
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -e ".[web]"
fi

# 3. Launch ------------------------------------------------------------------
echo "Manaless -> http://$HOST:$PORT"
exec "$PY" -m manaless.web --host "$HOST" --port "$PORT" "$@"
