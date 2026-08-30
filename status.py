"""Aggregate every gate's event log into live totals.

Occupancy is derived by counting rows, never held in memory, so a counter
process that crashed and restarted still produces correct totals.

    python status.py
    python status.py --watch 5
"""

import argparse
import csv
import datetime
import json
import time

import config


def read_gate(path):
    """Return (gate, in_count, out_count, last_event_time) for one event log."""
    gate = path.stem.replace("events_", "")
    ins = outs = 0
    last = None
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["direction"] == "in":
                ins += 1
            elif row["direction"] == "out":
                outs += 1
            last = row["timestamp"]
    return gate, ins, outs, last


def read_heartbeat(gate, now):
    """Return (age_seconds, fps) for a gate, or (None, None) if never seen."""
    path = config.heartbeat_file(gate)
    if not path.exists():
        return None, None
    beat = json.loads(path.read_text())
    updated = datetime.datetime.fromisoformat(beat["updated"])
    return (now - updated).total_seconds(), beat.get("fps")


def render():
    config.DATA_DIR.mkdir(exist_ok=True)
    logs = sorted(config.DATA_DIR.glob("events_*.csv"))
    if not logs:
        print(f"no event logs in {config.DATA_DIR} yet")
        return

    now = datetime.datetime.now()
    print(f"{'gate':<12}{'in':>7}{'out':>7}{'inside':>9}{'fps':>7}  health")
    print("-" * 62)

    total_in = total_out = 0
    for path in logs:
        gate, ins, outs, last = read_gate(path)
        total_in += ins
        total_out += outs
        age, fps = read_heartbeat(gate, now)

        if age is None:
            health = "never started"
        elif age > config.STALE_AFTER_SECONDS:
            # The counter process is gone, or its camera went unresponsive and
            # the loader is feeding it black frames. Either way it is not counting.
            health = f"STALE - no heartbeat for {int(age)}s"
        else:
            health = f"ok, last beat {int(age)}s ago"

        print(f"{gate:<12}{ins:>7}{outs:>7}{ins - outs:>9}"
              f"{(fps if fps is not None else 0):>7.1f}  {health}")
        if last:
            print(f"{'':<12}last crossing {last}")

    print("-" * 62)
    print(f"{'TOTAL':<12}{total_in:>7}{total_out:>7}{total_in - total_out:>9}")
    print(f"\nread at {now.isoformat(timespec='seconds')}")
    print("Occupancy is in minus out and drifts with every missed crossing. "
          "Treat it as an estimate, not a headcount.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=float, default=0,
                    help="refresh every N seconds instead of printing once")
    args = ap.parse_args()

    if not args.watch:
        render()
        return
    try:
        while True:
            print("\033[2J\033[H", end="")   # clear screen, cursor home
            render()
            time.sleep(args.watch)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
