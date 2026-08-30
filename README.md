# entry-counter

Counts people entering and exiting through one or more monitored gates, using an overhead camera per gate and logging every crossing with its direction and timestamp.

## Installation

Requires Python 3.10 or newer.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

On Linux and macOS the interpreter is at `.venv/bin/python` instead; substitute
it in every command below.

The `yolo11n.pt` weights (~5 MB) download automatically on first run.

### GPU support

The PyPI torch wheel for Windows is CPU-only. To use an NVIDIA GPU, reinstall
torch from the CUDA index after the step above:

```bash
.venv/Scripts/python -m pip install torch --index-url https://download.pytorch.org/whl/cu126
```

## Setup

### 1. Mount the cameras

Each gate needs one camera, mounted **overhead and pointing straight down** at
the opening. A top-down view is what keeps counting accurate when people pass
close together; an angled or eye-level view undercounts as soon as bodies
overlap. Aim for at least 15 fps at 720p, and enough light (or IR) that people
are clearly visible.

### 2. Check the machine can keep up

Every stream must sustain roughly 15 fps of inference. Below that, a walking
person spans too few frames to be counted reliably. Benchmark with as many
parallel streams as you have cameras, using a recording from one of them:

```bash
.venv/Scripts/python bench.py --streams 2 --source recording.mp4
```

If it reports `TOO SLOW`, use a CUDA build of torch on an NVIDIA GPU, run one
machine per gate, or reduce the number of streams per machine.

### 3. Place a counting line per gate

Each gate is identified by a name you choose. Run the placement tool against
that gate's camera:

```bash
.venv/Scripts/python preview.py --gate north --source rtsp://user:pass@10.0.0.5:554/stream
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
the start→end vector is IN, so a line drawn left-to-right counts upward
movement as IN — but read the arrow rather than deriving it, and press `f` if
it points the wrong way.

The line should span the full opening. `LineZone` only counts crossings between
the two endpoints, so anyone passing beyond an end is silently uncounted;
`count.py` warns at startup if the line stops short of the frame edges. Press
`t` to mark a partial line intentional and suppress that warning.

Lines are saved to `lines/<gate>.json` along with the resolution they were drawn
at, and are rescaled automatically if the stream resolution later differs.

Repeat for each gate.

## Use

### Running

One process per camera. Each writes only its own files, so gates never contend
and one failing camera cannot stop the others.

```bash
.venv/Scripts/python count.py --gate north --source rtsp://user:pass@10.0.0.5:554/stream
```

| Flag | Default | Purpose |
|---|---|---|
| `--gate` | `test` | Gate name; keys the line, event log and heartbeat |
| `--source` | `0` | Video file, webcam index, or stream URL |
| `--model` | `yolo11n.pt` | Use `yolo11s.pt` for accuracy over speed |
| `--conf` | `0.1` | Detection floor |
| `--min-crossing` | `3` | Frames a person may vanish for mid-crossing |
| `--no-show` | off | Headless, no preview window |
| `--save-video` | off | Write annotated `out_<gate>.mp4` (file sources only) |

To start every gate at once and restart any that exit, put the real stream URLs
in `run_gates.ps1` and run it:

```bash
./run_gates.ps1
```

### Reading the counts

```bash
.venv/Scripts/python status.py --watch 5
```

```
gate             in    out   inside    fps  health
--------------------------------------------------------------
north            84     31       53   20.4  ok, last beat 2s ago
south            67     22       45   19.8  ok, last beat 4s ago
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

Each counter writes `data/heartbeat_<gate>.json` every 5 seconds, and
`status.py` marks a gate `STALE` once its heartbeat is older than 60 seconds.
Check it periodically while the system is running.

### Data written

`data/events_<gate>.csv` records one row per crossing:

```
timestamp,gate,direction,tracker_id,video_time_s,frame
2026-08-28T14:03:11,north,in,7,412.30,12369
```

Totals are derived by counting rows rather than held in memory, so a counter
that is restarted resumes without losing anything already recorded. Only counts
and timestamps are stored; no video is written unless `--save-video` is passed.

## Tuning

| Symptom | Fix |
|---|---|
| In and out are swapped | `preview.py`, press `f`, then `p` |
| Counts lower than expected | Line does not span the opening; use `h` or `v` |
| Box flickers mid-crossing, trace looks fine, no count | Raise `--min-crossing` |
| People missed entirely | `--model yolo11s.pt` |
| Counting degrades when people bunch up | Camera is too low or too angled; mount higher and truly top-down |
| Too slow | Keep `yolo11n.pt`, use a GPU, or fewer streams per machine |

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
| `preview.py` | Place a gate's counting line. Requires only opencv. |
| `count.py` | One gate: detect, track, count, log crossings, emit heartbeat. |
| `status.py` | Aggregate all gates into totals and health. |
| `bench.py` | Measure sustained fps with N streams contending. |
| `config.py` | Paths, defaults, per-gate line load/save with rescaling. |
| `run_gates.ps1` | Start and auto-restart one process per gate. |
| `bytetrack.yaml` | Tracker settings tuned for an overhead camera. |
| `lines/<gate>.json` | Line, the resolution it was drawn at, the partial flag. |
| `data/events_<gate>.csv` | One row per crossing. |
| `data/heartbeat_<gate>.json` | Proof of life: last update, frames, fps. |
