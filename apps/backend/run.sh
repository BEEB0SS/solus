#!/bin/sh
# Start the Solus backend from the project venv, which has websockets,
# pyserial, and mujoco installed. Running a globally-installed uvicorn
# instead silently breaks WebSocket telemetry (upgrades 404).
cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/uvicorn ]; then
  echo "No venv found — creating one and installing requirements..."
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt || exit 1
fi

exec .venv/bin/uvicorn src.main:app --port 8000 "$@"
