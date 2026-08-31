# entry-counter

Counts people entering and exiting through a monitored gate, using an overhead camera and logging every crossing with its direction and timestamp.

## Installation

Requires Python 3.10 or newer.

### macOS

```bash
brew install python
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

On Apple Silicon this installs an arm64 build of torch with Metal (MPS)
acceleration available. Check it was picked up:

```bash
.venv/bin/python -c "import torch; print(torch.backends.mps.is_available())"
```

If that prints `True`, pass `--device mps` to `count.py` and `bench.py` for a
substantial speedup over CPU. Some operations silently fall back to CPU, so
benchmark both before deciding.

### Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

On a minimal Debian or Ubuntu install, OpenCV needs system libraries that are
not pulled in by pip:

```bash
sudo apt install -y libgl1 libglib2.0-0
```

Without a desktop session there is no window to draw into — run `count.py` with
`--no-show`, and place the counting line on a machine that has a display.

### Windows

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

The PyPI torch wheel for Windows is CPU-only. For an NVIDIA GPU, reinstall torch
from the CUDA index afterwards:

```bash
.venv/Scripts/python -m pip install torch --index-url https://download.pytorch.org/whl/cu126
```

### Interpreter paths

Commands below are written as `python`. Use the interpreter from the virtual
environment:

| Platform | Path |
|---|---|
| macOS, Linux | `.venv/bin/python` |
| Windows | `.venv/Scripts/python` |

The `yolo11n.pt` weights (~5 MB) download automatically on first run.

## Setup

### 1. Mount the camera

Mount it **overhead, pointing straight down** at the opening. A top-down view is
what keeps counting accurate when people pass close together; an angled or
eye-level view undercounts as soon as bodies overlap. Aim for at least 15 fps at
720p, and enough light (or IR) that people are clearly visible.

If the camera can pan or tilt, disable motion tracking, auto-patrol and any
follow feature. The counting line is stored in pixel coordinates, so if the head
moves the line no longer sits on the opening and counts go wrong silently.

### 2. Find the camera's stream

Vendors use different RTSP paths and rarely document them. `probe.py` tries the
common ones and reports what answers:

```bash
.venv/bin/python probe.py --host 192.168.1.50 --user admin --password secret
```

It prints resolution and **measured** frame rate for each working path, saves a
still so you can check the aim, and prints the `--source` value to use. Measured
fps is the number that matters — a camera advertising 30 fps often delivers far
less over wifi, and anything under ~15 is too slow.

RTSP frequently has to be switched on in the vendor's app first; some cameras
require creating a separate camera account before it works at all.

Streams are opened over TCP rather than the UDP default. Under wifi congestion
UDP silently drops packets, which shows up as torn frames and phantom detections
rather than as an error.

To use a locally attached webcam instead, pass `--source 0`. On macOS the
terminal application needs Camera access under System Settings → Privacy &
Security → Camera; without it the capture opens and returns black frames.

### 3. Check the machine can keep up

Inference must sustain roughly 15 fps. Below that, a walking person spans too few
frames to be counted reliably. Benchmark against a recording from the camera:

```bash
.venv/bin/python bench.py --source recording.mp4
```

On Apple Silicon, compare devices before committing:

```bash
.venv/bin/python bench.py --source recording.mp4 --device mps
.venv/bin/python bench.py --source recording.mp4 --device cpu
```

If it reports `TOO SLOW`, use a GPU (`--device mps` on Apple Silicon, a CUDA
build on NVIDIA), or a smaller input.

### 4. Place the counting line

```bash
.venv/bin/python preview.py --source "rtsp://user:pass@192.168.1.50:554/stream1"
```

| Key | Action |
|---|---|
| left click ×2 | set the line from point A to point B |
| `h` / `v` | horizontal / vertical line through the cursor, spanning the frame |
| `w` `a` `s` `d` | nudge the line |
| `f` | flip direction — swaps which side counts as IN |
| `t` | mark the line as deliberately partial |
| `n` `b` `.` `,` | step / jump through frames (video files only) |
| `p` | save |
| `q` | quit |

The green arrow shows which side counts as **IN**. Crossing towards the left of
the start→end vector is IN, so a line drawn left-to-right counts upward movement
as IN — but read the arrow rather than deriving it, and press `f` if it points
the wrong way.

The line should span the full opening. `LineZone` only counts crossings between
the two endpoints, so anyone passing beyond an end is silently uncounted;
`count.py` warns at startup if the line stops short of the frame edges. Press `t`
to mark a partial line intentional and suppress that warning.

The line is saved to `lines/main.json` along with the resolution it was drawn at,
and is rescaled automatically if the stream resolution later differs.

## Use

### Running

```bash
.venv/bin/python count.py --source "rtsp://user:pass@192.168.1.50:554/stream1"
```

| Flag | Default | Purpose |
|---|---|---|
| `--source` | `0` | Video file, webcam index, or stream URL |
| `--gate` | `main` | Gate name; keys the line, event log and heartbeat |
| `--model` | `yolo11n.pt` | Use `yolo11s.pt` for accuracy over speed |
| `--device` | auto | `cpu`, `mps` on Apple Silicon, or a CUDA index like `0` |
| `--conf` | `0.1` | Detection floor |
| `--min-crossing` | `3` | Frames a person may vanish for mid-crossing |
| `--no-show` | off | Headless, no preview window |
| `--save-video` | off | Write annotated `out_<gate>.mp4` (file sources only) |

To keep it running unattended and restart it if it exits:

```bash
chmod +x run_gate.sh
SOURCE="rtsp://user:pass@192.168.1.50:554/stream1" ./run_gate.sh
```

On Windows:

```bash
$env:SOURCE = "rtsp://user:pass@192.168.1.50:554/stream1"; .\run_gate.ps1
```

The stream URL is read from the environment rather than stored in the script, so
camera credentials never end up committed.

### Reading the counts

```bash
.venv/bin/python status.py --watch 5
```

```
gate             in    out   inside    fps  health
--------------------------------------------------------------
main            151     53       98   20.4  ok, last beat 2s ago
--------------------------------------------------------------
TOTAL           151     53       98
```

Occupancy is `in - out`. Every missed crossing is permanent, so it drifts over
long runs — take a baseline when the space is known to be empty, and reconcile
against a manual count periodically if the figure needs to be dependable.

### Monitoring for a dead camera

When a stream goes unresponsive the loader feeds black frames and reconnects in
the background: no crash, no detections, no counts. A quiet gate and a dead gate
produce identical numbers.

The counter writes `data/heartbeat_<gate>.json` every 5 seconds, and `status.py`
marks a gate `STALE` once its heartbeat is older than 60 seconds. Check it
periodically while the system is running.

### Data written

`data/events_<gate>.csv` records one row per crossing:

```
timestamp,gate,direction,tracker_id,video_time_s,frame
2026-08-28T14:03:11,main,in,7,412.30,12369
```

Totals are derived by counting rows rather than held in memory, so a counter that
is restarted resumes without losing anything already recorded. Only counts and
timestamps are stored; no video is written unless `--save-video` is passed.

### Adding a second camera

Run another process with a different `--gate`. The name keys the line, the event
log and the heartbeat, so two cameras never write to the same file, and
`status.py` sums across all of them:

```bash
GATE=side SOURCE="rtsp://user:pass@192.168.1.51:554/stream1" ./run_gate.sh
```

Place that gate's line first with `preview.py --gate side`. Streams contend for
the same machine, so re-run `bench.py --streams 2` before relying on it.

## Tuning

| Symptom | Fix |
|---|---|
| In and out are swapped | `preview.py`, press `f`, then `p` |
| Counts lower than expected | Line does not span the opening; use `h` or `v` |
| Box flickers mid-crossing, trace looks fine, no count | Raise `--min-crossing` |
| People missed entirely | `--model yolo11s.pt` |
| Counting degrades when people bunch up | Camera is too low or too angled; mount higher and truly top-down |
| Too slow | `--device mps` on Apple Silicon, a CUDA build on NVIDIA, or keep `yolo11n.pt` |
| Torn frames or phantom detections on wifi | Confirm TCP transport; prefer ethernet |
| Counts stop after the camera is moved | The line is in pixels: disable pan-tilt tracking and patrol, then re-place the line |
| `cv2.imshow` fails on Linux | No display; use `--no-show` |

### Dropped detections mid-crossing

The most confusing failure mode: the detection box flickers off for a few frames
while someone is on the line and they are never counted, even though the drawn
trace behind them looks unbroken. The trace comes from the annotator's own
history, so it hides the gap.

`LineZone` tolerates exactly `--min-crossing` dropped frames before discarding
that person's crossing state:

| dropped frames | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| `--min-crossing 1` (library default) | ok | miss | miss | miss | miss | miss |
| `--min-crossing 3` (default here) | ok | ok | ok | miss | miss | miss |
| `--min-crossing 5` | ok | ok | ok | ok | ok | miss |

Raising it only requires a person to be seen that many frames past the line
before counting, so keep it well below the number of frames a crossing takes.

Two settings reduce the dropouts themselves:

- `--conf` defaults to `0.1`, matching `track_low_thresh` in `bytetrack.yaml`.
  ByteTrack's second association pass over low-scoring boxes is what recovers a
  flickering detection, and it only sees boxes that survive this filter. Raising
  `--conf` above `0.1` disables that recovery. New tracks still require
  `new_track_thresh` (0.25), so weak boxes extend existing tracks but never
  invent people.
- `track_buffer` in `bytetrack.yaml` is raised to 60 (2 s at 30 fps) so someone
  who briefly vanishes keeps their track id rather than returning as a new
  person. An id change mid-crossing breaks counting outright, since the two
  halves are attributed to different people. Check for this in `--save-video`
  output: the `#n` label should not change as someone passes through. Lower it
  if crowding causes id switches between different people.

## Files

| File | Purpose |
|---|---|
| `probe.py` | Find a camera's RTSP path and measure its real frame rate. |
| `preview.py` | Place the counting line. Requires only opencv. |
| `count.py` | Detect, track, count, log crossings, emit heartbeat. |
| `status.py` | Totals and health, across every gate present. |
| `bench.py` | Measure sustained fps, optionally with several streams contending. |
| `config.py` | Paths, defaults, line load/save with rescaling. |
| `run_gate.sh` | Start and auto-restart the counter (macOS, Linux). |
| `run_gate.ps1` | Start and auto-restart the counter (Windows). |
| `bytetrack.yaml` | Tracker settings tuned for an overhead camera. |
| `lines/<gate>.json` | Line, the resolution it was drawn at, the partial flag. |
| `data/events_<gate>.csv` | One row per crossing. |
| `data/heartbeat_<gate>.json` | Proof of life: last update, frames, fps. |
