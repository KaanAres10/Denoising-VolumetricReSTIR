"""Render a whole dataset one frame per process, so VRAM holds one volume instead of all of them.

  python render_sequence_streamed.py dustShockwave [--frames N] [--acc 32] [--fps 24]

Each frame is rendered by its own Mogwai process (capture_frame.py) and the resulting PNG is
renamed to carry the animation frame index, so encode_video orders them correctly. Peak VRAM is
baseline + one frame rather than baseline + N frames, which is what lets a dataset longer than the
card run at all.

TRADE-OFF: no temporal ReSTIR reuse across animation frames -- every frame starts cold and
accumulates --acc frames on a static volume instead. Use capture_sequence.py when you need the
animated path's temporal behaviour; use this when you need length.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vdb_pipeline as vp
import encode_video

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parents[3]
MOGWAI = REPO / "build" / "windows-vs2022" / "bin" / "Release" / "Mogwai.exe"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--frames", type=int, default=None, help="how many frames (default: all ingested)")
    ap.add_argument("--acc", type=int, default=32, help="accumulation frames per animation frame")
    ap.add_argument("--fps", type=int, default=24)
    a = ap.parse_args()

    if not MOGWAI.exists():
        raise SystemExit(f"FAILED: {MOGWAI} not found")

    ds = vp.get_dataset(a.dataset)
    if a.frames:
        ds = dict(ds, num_frames=a.frames, playback_frames=None)
    frames = vp.frame_numbers(ds)

    out = REPO / "shots" / f"{a.dataset}_streamed"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    print(f"[streamed] {a.dataset}: {len(frames)} frames, {a.acc} accumulation frames each")
    for i, f in enumerate(frames, 1):
        env = dict(os.environ, VR_DATASET=a.dataset, VR_FRAME=str(f),
                   VR_ACC=str(a.acc), VR_OUT=str(out))
        r = subprocess.run([str(MOGWAI), "--script", str(SCRIPTS / "capture_frame.py")],
                           cwd=str(MOGWAI.parent), env=env,
                           capture_output=True, text=True)
        # Mogwai names captures after the RENDERED frame index, which is the same every process.
        # Rename to the ANIMATION frame index so encode_video's numeric sort is meaningful.
        produced = sorted(out.glob("frame.*.png"))
        produced = [p for p in produced if not p.name.startswith("f_")]
        if not produced:
            tail = (r.stdout or "")[-600:] + (r.stderr or "")[-600:]
            raise SystemExit(f"FAILED: frame {f} produced no capture (exit {r.returncode})\n{tail}")
        produced[0].rename(out / f"f_{a.dataset}.ToneMapper.dst.{f}.png")
        print(f"[{i}/{len(frames)}] frame {f} ok")

    mp4 = REPO / "shots" / f"{a.dataset}_streamed.mp4"
    encode_video.encode(out, mp4, fps=a.fps)
    print(f"[streamed] done -> {mp4}")


if __name__ == "__main__":
    main()
