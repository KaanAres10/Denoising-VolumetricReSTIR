"""The paper's five-denoiser table (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E5), from
run_five.sh's runs: for every setup, history (c200: M cap 200; ship: the shipped cap), config (m0 plain, m5 five
mutations) and channel (optix, oidn, relax, reblur and raw from the shared graph; rr from its own), the in-medium
relMSE of each kept frame (medium_metrics.relmse) and their mean, and the mean brightness over the reference's; per
setup, the reference's own relMSE.

    python five_scores.py <root> [--out <root>/five_denoisers/results.json]
"""
import argparse
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art  # noqa: E402
import five_runs  # noqa: E402
import m_corr as mc  # noqa: E402
import medium_metrics as mm  # noqa: E402


def schedule(run_dir):
    with open(os.path.join(run_dir, "c.schedule.json")) as fh:
        return json.load(fh)


def channels(run_dir):
    """{name: capture channel}: the shared graph's `channels` (raw included), else RR's single channel."""
    s = schedule(run_dir)
    return dict(s["channels"]) if s.get("channels") else {"rr": s["channel"]}


def frames(run_dir, channel):
    """The first capture of every chain, RGB; a missing one raises."""
    out = []
    for c in schedule(run_dir)["chains"]:
        path = os.path.join(run_dir, "c.%s.%d.exr" % (channel, c["frames"][0]))
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        out.append(mc.read_exr(path)[..., :3][..., ::-1].astype(np.float64))
    return out


def finished(run_dir):
    """Every channel's capture of every chain is there (a run stopped before it wrote its schedule has none)."""
    if not os.path.isfile(os.path.join(run_dir, "c.schedule.json")):
        return False
    return all(os.path.exists(os.path.join(run_dir, "c.%s.%d.exr" % (ch, c["frames"][0])))
               for ch in channels(run_dir).values() for c in schedule(run_dir)["chains"])


def run_dirs(root, label, hist, m):
    """One configuration's captures: the shared graph fd_<hist>_m<m> if it finished, else the split graphs
    fd<k>_<hist>_m<m> that re-ran it (FIVE_SETS), and RR's fr_<hist>_m<m>. A shared run that did not finish and was
    not re-run raises, as a missing frame does."""
    d = os.path.join(root, label)
    shared = os.path.join(d, "fd_%s_m%d" % (hist, m))
    split = sorted(n for n in os.listdir(d) if re.fullmatch(r"fd\d+_%s_m%d" % (hist, m), n))
    if os.path.isdir(shared) and (finished(shared) or not split):
        names = ["fd_%s_m%d" % (hist, m)]
    else:
        names = split
    names.append("fr_%s_m%d" % (hist, m))
    return [os.path.join(d, n) for n in names if os.path.isdir(os.path.join(d, n))]


def score(root, label):
    ref = art.reference(root, label)
    mask = np.load(os.path.join(root, label, "noreuse", "c.medium.npy"))
    out = {"ref_own_relmse": mm.own_relmse(os.path.join(root, label, "ref"), mask), "histories": {}}
    for hist in five_runs.HISTORIES:
        for m in (0, 5):
            for run_dir in run_dirs(root, label, hist, m):
                for name, ch in channels(run_dir).items():
                    imgs = frames(run_dir, ch)
                    rel = [mm.relmse(i, ref, mask) for i in imgs]
                    out["histories"].setdefault(hist, {}).setdefault("m%d" % m, {})[name] = {
                        "relmse": rel, "mean": float(np.mean(rel)),
                        "brightness": [mm.brightness(i, ref, mask) for i in imgs],
                        "run": os.path.relpath(run_dir, root).replace(os.sep, "/")}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    results = {}
    for label in five_runs.SETUPS:
        d = os.path.join(a.root, label)
        if os.path.isdir(d) and any(n.startswith(("fd", "fr")) for n in os.listdir(d)):
            results[label] = score(a.root, label)
    out = a.out or os.path.join(a.root, "five_denoisers", "results.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(results, fh, indent=1)
    for label, r in results.items():
        for hist, cfgs in r["histories"].items():
            if "m0" in cfgs and "m5" in cfgs:
                cuts = ["%s %+.0f%%" % (n, 100 * (cfgs["m5"][n]["mean"] / cfgs["m0"][n]["mean"] - 1))
                        for n in cfgs["m0"] if n in cfgs["m5"]]
                print("%-24s %-4s %s" % (label, hist, "  ".join(cuts)))
    print(out)
    return results


if __name__ == "__main__":
    main()
