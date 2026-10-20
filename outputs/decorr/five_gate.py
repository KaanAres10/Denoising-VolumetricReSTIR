"""Gate 2 of the paper's runs (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E4): one channel of one
run against one channel of another, frame by frame over the first run's captures.

    python five_gate.py <run A> <channel A> <run B> <channel B>

prints {"frames", "identical", "max_abs", "mean_abs"} as JSON (RGB, as captured).
"""
import json
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_corr as mc  # noqa: E402


def captures(run_dir):
    with open(os.path.join(run_dir, "c.schedule.json")) as fh:
        s = json.load(fh)
    return [f for c in s["chains"] for f in c["frames"]]


def compare(dir_a, ch_a, dir_b, ch_b):
    frames = captures(dir_a)
    if captures(dir_b) != frames:
        raise ValueError("the runs captured different frames: %s vs %s" % (frames, captures(dir_b)))
    identical, max_abs, total, n = 0, 0.0, 0.0, 0
    for f in frames:
        a = mc.read_exr(os.path.join(dir_a, "c.%s.%d.exr" % (ch_a, f)))[..., :3].astype(np.float64)
        b = mc.read_exr(os.path.join(dir_b, "c.%s.%d.exr" % (ch_b, f)))[..., :3].astype(np.float64)
        if a.shape != b.shape:
            raise ValueError("frame %d: %s vs %s" % (f, a.shape, b.shape))
        d = np.abs(a - b)
        identical += int(not d.any())
        max_abs = max(max_abs, float(d.max()))
        total += float(d.sum())
        n += d.size
    return {"frames": len(frames), "identical": identical, "max_abs": max_abs, "mean_abs": total / n}


if __name__ == "__main__":
    print(json.dumps(compare(*sys.argv[1:5])))
