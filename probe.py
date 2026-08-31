"""Find a camera's RTSP stream and check it is usable before wiring it in.

Camera vendors all use different RTSP paths and rarely document them, so this
tries the common ones, then reports resolution and measured frame rate for
whichever answers.

    python probe.py --host 192.168.1.50 --user admin --password secret
    python probe.py --host 192.168.1.50 --user admin --password secret --path /stream2

Measured fps is the number that matters: a camera advertising 30 fps may deliver
far less over wifi, and the counter needs roughly 15.

Run this from PowerShell. Git Bash rewrites a leading-slash argument such as
--path /stream1 into a Windows path before Python ever sees it; prefix it with a
second slash (//stream1) if you must run it there.
"""

import argparse
import os
import time
from urllib.parse import quote

# Must be set before the first capture is created. TCP transport matters over
# wifi: the UDP default silently drops packets under congestion, which arrives
# as torn frames and phantom detections rather than as an error.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402  (import after the env var above)

# Paths that answer on the widest range of consumer and prosumer cameras.
COMMON_PATHS = [
    ("/stream1", "Tapo main"),
    ("/stream2", "Tapo sub"),
    ("/h264Preview_01_main", "Reolink main"),
    ("/h264Preview_01_sub", "Reolink sub"),
    ("/Streaming/Channels/101", "Hikvision main"),
    ("/Streaming/Channels/102", "Hikvision sub"),
    ("/cam/realmonitor?channel=1&subtype=0", "Dahua/Imou/Amcrest main"),
    ("/cam/realmonitor?channel=1&subtype=1", "Dahua/Imou/Amcrest sub"),
    ("/axis-media/media.amp", "Axis"),
    ("/videoMain", "Foscam"),
    ("/live", "generic"),
    ("/live/ch0", "generic"),
    ("/onvif1", "generic ONVIF"),
    ("/11", "generic"),
]


def build_url(host, port, user, password, path):
    # Percent-encode the credentials. Vendor default passwords routinely contain
    # @ : / #, any of which silently reshapes the URL: "p@ss" makes everything
    # after the @ the hostname, so every path fails for no visible reason.
    credentials = f"{quote(user, safe='')}:{quote(password, safe='')}@" if user else ""
    return f"rtsp://{credentials}{host}:{port}{path}"


def measure(url, frames, timeout_ms):
    """Open a stream and measure it. Returns a dict, or None if it never opened."""
    # The timeouts have to be passed as open parameters: setting them with
    # .set() afterwards is too late, the constructor has already blocked.
    capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout_ms,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC, timeout_ms,
    ])
    if not capture.isOpened():
        capture.release()
        return None

    ok, frame = capture.read()
    if not ok or frame is None:
        capture.release()
        return None

    height, width = frame.shape[:2]
    reported = capture.get(cv2.CAP_PROP_FPS) or 0.0

    started = time.perf_counter()
    read = 0
    for _ in range(frames):
        ok, latest = capture.read()
        if not ok:
            break
        read += 1
        frame = latest
    elapsed = time.perf_counter() - started
    capture.release()

    return {
        "width": width,
        "height": height,
        "reported_fps": reported,
        "measured_fps": read / max(elapsed, 1e-6),
        "frames_read": read,
        "frame": frame,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True, help="camera IP address")
    ap.add_argument("--port", type=int, default=554)
    ap.add_argument("--user", default="", help="RTSP username, if the camera needs one")
    ap.add_argument("--password", default="")
    ap.add_argument("--path", help="test only this path instead of trying the common ones")
    ap.add_argument("--frames", type=int, default=60, help="frames to time")
    ap.add_argument("--timeout", type=int, default=5000, help="per-path timeout in ms")
    args = ap.parse_args()

    candidates = ([(args.path, "given")] if args.path
                  else COMMON_PATHS)

    print(f"probing {args.host}:{args.port} over TCP, {len(candidates)} path(s) to try\n")
    working = []

    for path, label in candidates:
        url = build_url(args.host, args.port, args.user, args.password, path)
        print(f"  {path:<45} ", end="", flush=True)
        result = measure(url, args.frames, args.timeout)
        if result is None:
            print("no")
            continue
        print(f"OK  {result['width']}x{result['height']}  "
              f"{result['measured_fps']:.1f} fps measured "
              f"({result['reported_fps']:.0f} reported)  [{label}]")
        working.append((path, url, result))

    if not working:
        print("\nNothing answered. Things to check, in order:")
        print("  - RTSP may need switching on in the vendor app. Tapo, for one, needs a")
        print("    separate camera account created before RTSP works at all.")
        print("  - Confirm the IP and that the camera is on the same network.")
        print("  - Some cameras use a non-standard port; try --port 8554 or --port 10554.")
        print("  - If the vendor documents a path, pass it with --path.")
        raise SystemExit(1)

    # Prefer the highest resolution stream that still clears the frame rate floor.
    usable = [w for w in working if w[2]["measured_fps"] >= 15]
    best = max(usable or working, key=lambda w: w[2]["width"] * w[2]["height"])
    path, url, result = best

    still = f"probe_{args.host.replace('.', '_')}.jpg"
    cv2.imwrite(still, result["frame"])

    print(f"\nsaved a frame to {still} - check the camera is aimed straight down "
          f"at the opening.\n")
    print(f"use: --source \"{url}\"")

    if result["measured_fps"] < 15:
        print(f"\nwarning: {result['measured_fps']:.1f} fps measured, below the ~15 fps "
              f"the counter needs. Try a lower-resolution sub-stream, move the camera "
              f"closer to the access point, or use ethernet.")


if __name__ == "__main__":
    main()
