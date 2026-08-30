"""Count people crossing a line at one gate, from a file, webcam or RTSP stream.

One process per camera. Each crossing is appended to data/events_<gate>.csv as
its own row, so occupancy is a query over the log rather than a number held in
memory -- restarting mid-event loses nothing.

    python count.py --gate north --source rtsp://user:pass@10.0.0.5:554/stream
    python count.py --gate test --source footage/entrance.mp4 --save-video
"""

import argparse
import csv
import datetime
import json
import time

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO

import config


def with_tracker_ids(detections):
    """Guarantee a tracker_id field on the detections.

    Ultralytics leaves boxes.id as None on frames where nothing is tracked
    (typically the empty frames before the first person walks in). Both
    LineZone and the annotators require the field to be present, so drop those
    untracked boxes and hand back an empty-but-well-formed Detections.
    """
    if detections.tracker_id is not None:
        return detections
    empty = sv.Detections.empty()
    empty.tracker_id = np.empty(0, dtype=int)
    return empty


def warn_if_line_is_short(line, width, height):
    """LineZone only counts crossings between the two endpoints.

    A line that stops short of the frame edges silently ignores anyone who
    passes beyond its ends, which looks like undercounting rather than an error.
    """
    margin_x, margin_y = width * 0.02, height * 0.02

    def touches_border(point):
        x, y = point
        return (x <= margin_x or x >= width - margin_x
                or y <= margin_y or y >= height - margin_y)

    if not (touches_border(line.start) and touches_border(line.end)):
        print(f"warning: line {line.start} -> {line.end} does not reach the edges of "
              f"the {width}x{height} frame. Anyone crossing past its ends is not "
              f"counted. Re-run preview.py and press h or v to span the full frame, "
              f"or t to mark it deliberately partial.")


def open_event_log(gate):
    """Append-mode writer for this gate's event log, header written once."""
    config.DATA_DIR.mkdir(exist_ok=True)
    path = config.events_file(gate)
    is_new = not path.exists()
    handle = path.open("a", newline="", encoding="utf-8")
    writer = csv.writer(handle)
    if is_new:
        writer.writerow(config.EVENT_HEADER)
    return handle, writer


def write_heartbeat(gate, source, frames, fps, in_count, out_count):
    """Proof of life for status.py.

    A camera that goes unresponsive is fed black frames by the ultralytics
    loader -- no crash, no detections, no counts. Without a heartbeat that
    failure is indistinguishable from a quiet gate.
    """
    config.DATA_DIR.mkdir(exist_ok=True)
    config.heartbeat_file(gate).write_text(json.dumps({
        "gate": gate,
        "source": str(source),
        "updated": datetime.datetime.now().isoformat(timespec="seconds"),
        "frames": frames,
        "fps": round(fps, 1),
        "in_since_start": in_count,
        "out_since_start": out_count,
    }, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", default="test", help="gate name; keys the line, log and heartbeat")
    ap.add_argument("--source", default="0", help="video file, webcam index, or stream URL")
    ap.add_argument("--model", default=config.MODEL)
    ap.add_argument("--conf", type=float, default=config.CONF,
                    help="detection floor; keep at or below the tracker's track_low_thresh")
    ap.add_argument("--min-crossing", type=int, default=config.MIN_CROSSING,
                    help="frames a person may vanish for mid-crossing and still be counted")
    ap.add_argument("--no-show", action="store_true", help="run headless, no preview window")
    ap.add_argument("--save-video", action="store_true",
                    help="write an annotated out_<gate>.mp4 (file sources only)")
    args = ap.parse_args()

    source = config.parse_source(args.source)
    live = config.is_live(source)

    # Probe one frame so the line can be scaled to this source's resolution.
    probe = cv2.VideoCapture(source)
    if not probe.isOpened():
        raise SystemExit(f"could not open source: {args.source}")
    ok, frame = probe.read()
    if not ok:
        raise SystemExit("could not read a frame from the source")
    height, width = frame.shape[:2]
    fps = probe.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = 0 if live else int(probe.get(cv2.CAP_PROP_FRAME_COUNT))
    probe.release()

    line = config.load_line(args.gate, width, height)
    print(f"gate '{args.gate}'  {width}x{height}  line from {line.origin}: "
          f"{line.start} -> {line.end}")
    if line.origin == "default":
        print(f"no saved line for this gate - using a horizontal line across mid-frame. "
              f"Run preview.py --gate {args.gate} to place it properly.")
    if line.partial:
        print("line is marked partial: crossings past its ends are ignored on purpose.")
    else:
        warn_if_line_is_short(line, width, height)

    model = YOLO(args.model)
    line_zone = sv.LineZone(
        start=sv.Point(*line.start),
        end=sv.Point(*line.end),
        # A single centre anchor is the robust choice for an overhead view; the
        # default (all four box corners) misses people whose box straddles the line.
        triggering_anchors=[sv.Position.CENTER],
        # Tolerates this many dropped frames while a person is on the line. At
        # the library default of 1, a two-frame detection dropout loses the
        # count entirely, even though the drawn trace looks continuous.
        minimum_crossing_threshold=args.min_crossing,
    )

    # Colour by track id, not class: every detection here is class "person",
    # so a class lookup would paint everyone the same colour.
    lookup = sv.annotators.utils.ColorLookup.TRACK
    box_annotator = sv.BoxAnnotator(thickness=2, color_lookup=lookup)
    label_annotator = sv.LabelAnnotator(text_scale=0.5, color_lookup=lookup)
    trace_annotator = sv.TraceAnnotator(trace_length=40, color_lookup=lookup)
    line_annotator = sv.LineZoneAnnotator(thickness=2, text_scale=0.6)

    writer = None
    if args.save_video:
        if live:
            print("--save-video is only supported for file sources; ignoring.")
        else:
            writer = cv2.VideoWriter(str(config.ROOT / f"out_{args.gate}.mp4"),
                                     cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))

    handle, event_writer = open_event_log(args.gate)
    frame_index = 0
    started = time.perf_counter()
    last_heartbeat = 0.0
    elapsed = 0.0

    try:
        # Ultralytics runs ByteTrack internally; persist=True keeps ids stable
        # across the stream. For live sources its loader already keeps only the
        # newest frame and reconnects a dropped stream, so no grabber thread here.
        for result in model.track(source=source, stream=True, persist=True,
                                  conf=args.conf, tracker=str(config.ROOT / config.TRACKER),
                                  classes=[config.PERSON_CLASS], verbose=False):
            frame_index += 1
            detections = with_tracker_ids(sv.Detections.from_ultralytics(result))
            crossed_in, crossed_out = line_zone.trigger(detections)

            # One row per actual crossing, tagged with the track that made it.
            stamp = datetime.datetime.now().isoformat(timespec="seconds")
            for mask, direction in ((crossed_in, "in"), (crossed_out, "out")):
                for i in np.flatnonzero(mask):
                    track = int(detections.tracker_id[i])
                    event_writer.writerow([stamp, args.gate, direction, track,
                                           round(frame_index / fps, 2), frame_index])
                    handle.flush()
                    print(f"[{args.gate}] {direction:3s} track #{track}  "
                          f"in {line_zone.in_count} out {line_zone.out_count} "
                          f"inside {line_zone.in_count - line_zone.out_count}")

            elapsed = time.perf_counter() - started
            if elapsed - last_heartbeat >= config.HEARTBEAT_SECONDS:
                write_heartbeat(args.gate, args.source, frame_index,
                                frame_index / max(elapsed, 1e-6),
                                line_zone.in_count, line_zone.out_count)
                last_heartbeat = elapsed

            if args.no_show and writer is None:
                continue

            canvas = result.orig_img.copy()
            canvas = trace_annotator.annotate(canvas, detections=detections)
            canvas = box_annotator.annotate(canvas, detections=detections)
            canvas = label_annotator.annotate(
                canvas, detections=detections,
                labels=[f"#{tid}" for tid in detections.tracker_id],
            )
            canvas = line_annotator.annotate(canvas, line_counter=line_zone)

            if writer is not None:
                writer.write(canvas)
            if not args.no_show:
                cv2.imshow(f"gate {args.gate}", canvas)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        print("\nstopped by user")
    finally:
        elapsed = time.perf_counter() - started
        write_heartbeat(args.gate, args.source, frame_index,
                        frame_index / max(elapsed, 1e-6),
                        line_zone.in_count, line_zone.out_count)
        handle.close()
        if writer is not None:
            writer.release()
        cv2.destroyAllWindows()

    print("\n--- summary ---")
    print(f"gate             : {args.gate}")
    print(f"frames processed : {frame_index}" + (f" / {total_frames}" if total_frames else ""))
    print(f"elapsed          : {elapsed:.1f}s  ({frame_index / max(elapsed, 1e-6):.1f} fps)")
    print(f"in               : {line_zone.in_count}")
    print(f"out              : {line_zone.out_count}")
    print(f"inside           : {line_zone.in_count - line_zone.out_count}")
    print(f"events           : {config.events_file(args.gate)}")


if __name__ == "__main__":
    main()
