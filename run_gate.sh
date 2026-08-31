#!/usr/bin/env bash
# Start the counter and restart it if it exits. macOS and Linux.
#
#   chmod +x run_gate.sh          # once
#   SOURCE="rtsp://user:pass@192.168.1.50:554/stream1" ./run_gate.sh
#
# The stream URL comes from the environment so real camera credentials never
# have to be written into a tracked file. Override GATE too if you run more
# than one camera; each needs its own name.
#
# Watch the totals from another terminal with:
#   .venv/bin/python status.py --watch 5

set -uo pipefail
cd "$(dirname "$0")"

GATE="${GATE:-main}"
SOURCE="${SOURCE:-}"
PYTHON="${PYTHON:-.venv/bin/python}"

if [ -z "$SOURCE" ]; then
    echo "SOURCE is not set. Example:" >&2
    echo "  SOURCE=\"rtsp://user:pass@192.168.1.50:554/stream1\" ./run_gate.sh" >&2
    exit 1
fi

if [ ! -x "$PYTHON" ]; then
    echo "no interpreter at $PYTHON - create the venv first:" >&2
    echo "  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
    exit 1
fi

if [ ! -f "lines/$GATE.json" ]; then
    echo "warning: no lines/$GATE.json. Place the counting line first:" >&2
    echo "  $PYTHON preview.py --gate $GATE --source \"$SOURCE\"" >&2
fi

# Ctrl-C should stop the supervisor, not just the current child.
trap 'echo; echo "stopped"; exit 0' INT TERM

while true; do
    "$PYTHON" count.py --gate "$GATE" --source "$SOURCE" --no-show
    echo "gate $GATE exited, restarting in 5s" >&2
    sleep 5
done
