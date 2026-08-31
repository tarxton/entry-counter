"""Measure whether this machine can run N camera streams at once.

Runs N inference workers in parallel against the same clip, so the number you
get includes the contention of running them together -- benchmarking one stream
and multiplying is optimistic to the point of useless.

    python bench.py --source recording.mp4
    python bench.py --source recording.mp4 --device mps

A live stream is dropped to whatever fps inference sustains, so the result is
the fps each camera will really be tracked at.
"""

import argparse
import multiprocessing as mp
import pathlib
import time

import config

TARGET_FPS = 15   # below this, a walking person spans too few frames to count reliably


def worker(index, source, model_name, conf, frames_to_run, device, results):
    """Run inference on one stream and report sustained fps."""
    from ultralytics import YOLO

    model = YOLO(model_name)
    started = None
    done = 0
    for _ in model.track(source=source, stream=True, persist=True, conf=conf,
                         tracker=str(config.ROOT / config.TRACKER),
                         classes=[config.PERSON_CLASS], device=device, verbose=False):
        if started is None:
            started = time.perf_counter()   # start timing after model warm-up
            continue
        done += 1
        if done >= frames_to_run:
            break
    elapsed = time.perf_counter() - started
    results[index] = done / max(elapsed, 1e-6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--streams", type=int, default=1, help="cameras to simulate")
    ap.add_argument("--source", default=str(config.FOOTAGE_DIR / "sample.mp4"),
                    help="clip or stream to benchmark against")
    ap.add_argument("--model", default=config.MODEL)
    ap.add_argument("--conf", type=float, default=config.CONF)
    ap.add_argument("--device", default=None,
                    help="cpu, mps (Apple Silicon), or a CUDA index like 0")
    ap.add_argument("--frames", type=int, default=100, help="frames each worker processes")
    args = ap.parse_args()

    if (not config.is_live(config.parse_source(args.source))
            and not pathlib.Path(args.source).exists()):
        raise SystemExit(f"no such clip: {args.source}\n"
                         f"Pass --source with a recording from one of your cameras, "
                         f"or a stream URL.")

    print(f"benchmarking {args.streams} parallel stream(s) with {args.model} "
          f"on {args.source}\n")

    with mp.Manager() as manager:
        results = manager.dict()
        procs = [mp.Process(target=worker,
                            args=(i, args.source, args.model, args.conf, args.frames,
                                  args.device, results))
                 for i in range(args.streams)]
        wall = time.perf_counter()
        for p in procs:
            p.start()
        for p in procs:
            p.join()
        wall = time.perf_counter() - wall
        per_stream = [results[i] for i in sorted(results)]

    if len(per_stream) < args.streams:
        raise SystemExit(f"only {len(per_stream)} of {args.streams} workers reported a "
                         f"result; the rest failed. Their tracebacks are above.")

    for i, fps in enumerate(per_stream):
        print(f"  stream {i}: {fps:5.1f} fps")
    slowest = min(per_stream)
    print(f"\nslowest stream : {slowest:.1f} fps")
    print(f"wall clock     : {wall:.1f}s")

    if slowest >= TARGET_FPS:
        headroom = slowest / TARGET_FPS
        print(f"\nOK. Every stream clears the {TARGET_FPS} fps floor, {headroom:.1f}x headroom.")
    else:
        print(f"\nTOO SLOW. Streams need about {TARGET_FPS} fps for reliable counting; "
              f"the slowest is {slowest:.1f}.")
        print("Options, cheapest first: a CUDA torch build on an NVIDIA GPU, "
              "one machine (or Jetson) per gate, or a smaller model.")


if __name__ == "__main__":
    main()
