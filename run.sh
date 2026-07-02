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
if [ -z "$PY" ]; then
  echo "venv created but no python found under .venv — check the venv layout." >&2
  exit 1
fi

# 2. Dependencies ------------------------------------------------------------
# The multipart package is importable as either `python_multipart` (current) or
# the deprecated `multipart` alias; probe the new name first so a warm launch
# doesn't trigger a full reinstall once the alias is removed upstream.
have_multipart() {
  "$PY" -c "import python_multipart" 2>/dev/null || "$PY" -c "import multipart" 2>/dev/null
}
if ! "$PY" -c "import manaless, uvicorn, fastapi, jinja2" 2>/dev/null || ! have_multipart; then
  echo "Installing dependencies (editable + [web] extra)..."
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -e ".[web]"
fi

# 3. Launch ------------------------------------------------------------------
echo "Manaless -> http://$HOST:$PORT"
exec "$PY" -m manaless.web --host "$HOST" --port "$PORT" "$@"
