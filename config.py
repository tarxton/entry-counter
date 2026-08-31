"""Shared paths and defaults for the entry counter.

Everything is keyed by a gate name, so each camera gets its own line, its own
event log and its own heartbeat, and the processes never touch the same file.
"""

import json
import os
from collections import namedtuple
from pathlib import Path

# Read by OpenCV's FFMPEG backend when a capture is created. TCP transport
# matters over wifi: the UDP default silently drops packets under congestion,
# which arrives as torn frames and phantom detections rather than as an error.
# The timeout keys (microseconds) stop a dead camera hanging the process
# forever; both spellings are set because ffmpeg renamed stimeout to timeout,
# and an unused key is simply ignored.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                      "rtsp_transport;tcp|timeout;5000000|stimeout;5000000")

ROOT = Path(__file__).parent
FOOTAGE_DIR = ROOT / "footage"
LINES_DIR = ROOT / "lines"
DATA_DIR = ROOT / "data"

MODEL = "yolo11n.pt"        # swap to yolo11s.pt if the nano model misses people
# Deliberately low. ByteTrack's second association pass over low-scoring boxes
# (track_low_thresh 0.1) is what recovers a person whose detection flickers
# mid-crossing, and it only sees boxes that survive this filter. New tracks
# still need new_track_thresh 0.25, so weak boxes extend tracks but never
# invent people.
CONF = 0.1
MIN_CROSSING = 3            # dropped frames tolerated mid-crossing
TRACKER = "bytetrack.yaml"
PERSON_CLASS = 0            # COCO class id for "person"

HEARTBEAT_SECONDS = 5       # how often a running counter reports it is alive
STALE_AFTER_SECONDS = 60    # older than this and status.py calls the gate dead

# elapsed_s is wall-clock seconds since the counter started. It is not derived
# from frame_index, because a live source drops frames to keep up and the two
# diverge without bound.
EVENT_HEADER = ["timestamp", "gate", "direction", "tracker_id", "elapsed_s", "frame"]

Line = namedtuple("Line", "start end partial origin")


def parse_source(source):
    """Turn a CLI --source value into something OpenCV/Ultralytics accepts.

    "0" -> webcam index 0, anything else stays a string (file path or URL).
    """
    return int(source) if str(source).isdigit() else str(source)


def is_live(source):
    """True for a camera or network stream, False for a video file on disk."""
    return isinstance(source, int) or str(source).startswith(
        ("rtsp", "rtmp", "http", "udp"))


def write_json_atomic(path, payload):
    """Write JSON so a concurrent reader never sees a partial file.

    Path.write_text truncates and then writes, leaving a window in which a
    reader gets invalid JSON. Writing a sibling temp file and renaming it makes
    the swap atomic on both POSIX and Windows.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def line_file(gate):
    return LINES_DIR / f"{gate}.json"


def events_file(gate):
    return DATA_DIR / f"events_{gate}.csv"


def heartbeat_file(gate):
    return DATA_DIR / f"heartbeat_{gate}.json"


def save_line(gate, start, end, frame_width, frame_height, partial=False):
    """Store a gate's counting line together with the resolution it was drawn at.

    partial=True marks a line that deliberately covers only part of the opening
    (useful when testing, so you can walk back through the uncovered half
    without it registering). It only suppresses a warning.
    """
    LINES_DIR.mkdir(exist_ok=True)
    write_json_atomic(line_file(gate), {
        "start": [int(start[0]), int(start[1])],
        "end": [int(end[0]), int(end[1])],
        "width": int(frame_width),
        "height": int(frame_height),
        "partial": bool(partial),
    })


def load_line(gate, frame_width, frame_height):
    """Load a gate's line, rescaled if the footage is a different resolution.

    Falls back to a horizontal line across the middle of the frame. `origin`
    says which of those happened.
    """
    path = line_file(gate)
    if not path.exists():
        mid = frame_height // 2
        return Line((0, mid), (frame_width, mid), False, "default")

    data = json.loads(path.read_text())
    fx = frame_width / data["width"]
    fy = frame_height / data["height"]
    sx, sy = data["start"]
    ex, ey = data["end"]
    return Line(
        (round(sx * fx), round(sy * fy)),
        (round(ex * fx), round(ey * fy)),
        bool(data.get("partial", False)),
        str(path.name),
    )
