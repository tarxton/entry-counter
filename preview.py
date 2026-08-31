"""Place the counting line by eye, then save it for count.py.

Only needs opencv, so you can aim the camera and set the line while the
ultralytics/torch install is still downloading.

    python preview.py --source rtsp://user:pass@10.0.0.5:554/stream1
    python preview.py --source recording.mp4

Controls
    left click x2   set the line from point A to point B
    h / v           horizontal / vertical line through the cursor
    w / s           nudge the line up / down
    a / d           nudge the line left / right
    f               flip direction (swaps which side counts as IN)
    t               mark the line as deliberately partial (silences the
                    "does not reach the frame edges" warning in count.py)
    n / b           next / previous frame        (video files)
    . / ,           jump 30 frames forward / back (video files)
    p               save to line.json
    q               quit
"""

import argparse

import cv2

import config

NUDGE = 5
state = {"pending": None, "start": None, "end": None, "cursor": (0, 0), "partial": False}


def on_mouse(event, x, y, flags, userdata):
    state["cursor"] = (x, y)
    if event != cv2.EVENT_LBUTTONDOWN:
        return
    if state["pending"] is None:
        state["pending"] = (x, y)
    else:
        state["start"], state["end"] = state["pending"], (x, y)
        state["pending"] = None


def in_side_arrow(start, end):
    """Midpoint and tip of an arrow pointing at the side supervision counts as IN.

    Verified against supervision 0.30: for a line drawn start -> end, crossing
    towards the LEFT of that vector counts as IN. In image coordinates (y grows
    downward) that direction is (dy, -dx).
    """
    mx, my = (start[0] + end[0]) // 2, (start[1] + end[1]) // 2
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = max((dx * dx + dy * dy) ** 0.5, 1e-6)
    nx, ny = dy / length, -dx / length
    return (mx, my), (int(mx + nx * 60), int(my + ny * 60))


def draw(frame, start, end):
    canvas = frame.copy()
    cv2.line(canvas, start, end, (0, 255, 255), 2)
    tail, tip = in_side_arrow(start, end)
    cv2.arrowedLine(canvas, tail, tip, (0, 255, 0), 2, tipLength=0.3)
    cv2.putText(canvas, "IN", (tip[0] + 6, tip[1] + 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    if state["pending"]:
        cv2.circle(canvas, state["pending"], 5, (0, 255, 255), -1)
    flag = "  PARTIAL" if state["partial"] else ""
    cv2.putText(canvas, f"{start} -> {end}{flag}   [p] save  [f] flip  [t] partial  [q] quit",
                (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", default="main", help="gate name; the line is saved as lines/<gate>.json")
    ap.add_argument("--source", default="0", help="video file, webcam index, or stream URL")
    args = ap.parse_args()

    source = config.parse_source(args.source)
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"could not open source: {args.source}")

    is_file = not isinstance(source, int) and not str(source).startswith(("rtsp", "http"))
    ok, frame = cap.read()
    if not ok:
        raise SystemExit("could not read a frame from the source")

    height, width = frame.shape[:2]
    line = config.load_line(args.gate, width, height)
    state["start"], state["end"], state["partial"] = line.start, line.end, line.partial
    print(f"gate '{args.gate}'  {width}x{height}  line from {line.origin}")

    cv2.namedWindow("preview")
    cv2.setMouseCallback("preview", on_mouse)

    while True:
        if not is_file:                      # live source: keep pulling frames
            ok, latest = cap.read()
            if ok:
                frame = latest

        cv2.imshow("preview", draw(frame, state["start"], state["end"]))
        key = cv2.waitKey(1 if not is_file else 30) & 0xFF
        cx, cy = state["cursor"]

        if key == ord("q"):
            break
        elif key == ord("p"):
            config.save_line(args.gate, state["start"], state["end"], width, height,
                             state["partial"])
            print(f"saved {state['start']} -> {state['end']}"
                  f"{' (partial)' if state['partial'] else ''} to "
                  f"{config.line_file(args.gate)}")
        elif key == ord("h"):
            state["start"], state["end"] = (0, cy), (width, cy)
        elif key == ord("v"):
            state["start"], state["end"] = (cx, 0), (cx, height)
        elif key == ord("t"):
            state["partial"] = not state["partial"]
        elif key == ord("f"):
            state["start"], state["end"] = state["end"], state["start"]
        elif key in (ord("w"), ord("s"), ord("a"), ord("d")):
            dx = NUDGE * ((key == ord("d")) - (key == ord("a")))
            dy = NUDGE * ((key == ord("s")) - (key == ord("w")))
            state["start"] = (state["start"][0] + dx, state["start"][1] + dy)
            state["end"] = (state["end"][0] + dx, state["end"][1] + dy)
        elif is_file and key in (ord("n"), ord("b"), ord("."), ord(",")):
            step = {ord("n"): 1, ord("b"): -1, ord("."): 30, ord(","): -30}[key]
            target = max(0, int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1 + step)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            ok, latest = cap.read()
            if ok:
                frame = latest

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
