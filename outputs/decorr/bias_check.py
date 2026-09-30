"""Per-channel image mean of each config against a baseline (no reuse), with error bars from the spread of
chain means: frames of one chain are correlated, chains are not. How a biased move shows (the env re-selection's
-0.44% on the plume, spec V-B9).

    python bias_check.py <root> <baseline> <config> [<config> ...]

Each <root>/<name> holds a correlation_pose.py capture (c.schedule.json and its accumulated_color EXRs).
"""
import json
import os
import sys

import numpy as np

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")


def chain_means(frame_means, chains):
    """(chains, 3): the mean over each chain's captured frames present in frame_means (frame -> RGB mean)."""
    return np.array([np.mean([frame_means[f] for f in c if f in frame_means], axis=0) for c in chains])


def relative_bias(conf, base):
    """Relative per-channel difference of the two configs' means and its standard error, from their chain means."""
    m, b = conf.mean(0), base.mean(0)
    var = conf.var(0, ddof=1) / len(conf) + (m / b) ** 2 * base.var(0, ddof=1) / len(base)
    return m / b - 1, np.sqrt(var) / b


def load(run_dir):
    import cv2
    sched = json.load(open(os.path.join(run_dir, "c.schedule.json")))
    chains = [c["frames"] for c in sched["chains"]]
    frames = {}
    for f in (f for c in chains for f in c):
        p = os.path.join(run_dir, "c.%s.%d.exr" % (sched["channel"], f))
        img = cv2.imread(p, cv2.IMREAD_UNCHANGED)
        if img is not None:
            img = np.nan_to_num(img[..., :3][..., ::-1].astype(np.float64), posinf=0.0)
            frames[f] = img.reshape(-1, 3).mean(0)
    return chain_means(frames, chains), len(frames)


def main(argv):
    root, names = argv[1], argv[2:]
    base, n = load(os.path.join(root, names[0]))
    print("%-22s n=%d  (baseline)" % (names[0], n))
    for name in names[1:]:
        conf, n = load(os.path.join(root, name))
        bias, se = relative_bias(conf, base)
        print("%-22s n=%d  RGB vs %s %s   (+- %s, 1 s.e. over chains)" % (
            name, n, names[0], " ".join("%+.2f%%" % (100 * v) for v in bias), " ".join("%.2f%%" % (100 * v) for v in se)))


if __name__ == "__main__":
    main(sys.argv)
