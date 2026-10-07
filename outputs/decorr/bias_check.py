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


def paired_relative_bias(conf, base):
    """relative_bias for configs whose chain i shares chain i's seeds (correlation_pose.py seeds chain i with
    VR_SEED_BASE + i * stride in every config): the same estimate, with the error bar from the per-chain residuals of
    the linearised ratio, conf_i - r base_i, so the chain noise both configs share cancels instead of counting twice."""
    if conf.shape != base.shape:
        raise ValueError("paired chains must match: %s vs %s" % (conf.shape, base.shape))
    m, b = conf.mean(0), base.mean(0)
    r = m / b
    return r - 1, (conf - r * base).std(0, ddof=1) / np.sqrt(len(conf)) / b


def reference_bias(conf, ref_mean):
    """A config's mean against a converged reference's (per channel): the error bar is the config's chain spread."""
    return conf.mean(0) / ref_mean - 1, conf.std(0, ddof=1) / np.sqrt(len(conf)) / ref_mean


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


def chains_for(root, name, saved=None):
    """A config's chain means and frame count: from saved (a --save JSON) when it has the config -- its EXRs may be
    gone -- else from root/name."""
    if saved and name in saved:
        return np.array(saved[name], dtype=np.float64), "saved"
    return load(os.path.join(root, name))


def pct(v):
    return " ".join("%+.2f%%" % (100 * x) for x in v)


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="per-channel bias of configs against a baseline, chain-level errors")
    ap.add_argument("root")
    ap.add_argument("names", nargs="+", help="baseline first")
    ap.add_argument("--paired", action="store_true", help="the configs share their chains' seeds (pair chain i)")
    ap.add_argument("--ref", help="a converged reference EXR: also each config's mean against it")
    ap.add_argument("--save", help="write every config's chain means here (JSON), for re-analysis after pruning")
    ap.add_argument("--saved", help="a --save JSON: the configs it has are read from it (their EXRs may be gone)")
    a = ap.parse_args(argv[1:])
    saved = json.load(open(a.saved)) if a.saved else None
    means = {}
    base, n = chains_for(a.root, a.names[0], saved)
    means[a.names[0]] = base
    print("%-22s n=%s  (baseline)" % (a.names[0], n))
    for name in a.names[1:]:
        conf, n = chains_for(a.root, name, saved)
        means[name] = conf
        bias, se = (paired_relative_bias if a.paired else relative_bias)(conf, base)
        print("%-22s n=%s  RGB vs %s %s   (+- %s, 1 s.e. over chains%s)" % (
            name, n, a.names[0], pct(bias), " ".join("%.2f%%" % (100 * v) for v in se), ", paired" if a.paired else ""))
    if a.ref:
        import cv2
        ref = cv2.imread(a.ref, cv2.IMREAD_UNCHANGED)[..., :3][..., ::-1].astype(np.float64).reshape(-1, 3).mean(0)
        for name, conf in means.items():
            bias, se = reference_bias(conf, ref)
            print("%-22s vs reference %s   (+- %s)" % (name, pct(bias), " ".join("%.2f%%" % (100 * v) for v in se)))
    if a.save:
        with open(a.save, "w") as fh:
            json.dump({k: v.tolist() for k, v in means.items()}, fh)


if __name__ == "__main__":
    main(sys.argv)
