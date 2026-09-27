"""Delete a correlation run's captures once m_corr.py has scored it, keeping a few for the sheets.

Captures are uncompressed float32 EXRs (~25 MB a frame at 1080p) and a run holds ~100 of them per
channel, so the study cannot keep them. Only the files the run's schedule names are touched: the first
capture of the first `keep_chains` chains and of the burst survive, in every channel.

    python prune.py <run_dir> <tag> [--keep-chains 2]
"""
import argparse
import json
import os

IDENTITY = "VolumetricReSTIR.sampleIdentity"


def prune(run_dir, tag, keep_chains=2):
    with open(os.path.join(run_dir, tag + ".schedule.json")) as fh:
        sched = json.load(fh)
    channels = (sched.get("channel", "VolumetricReSTIR.accumulated_color"), IDENTITY)
    runs = list(sched["chains"]) + ([sched["burst"]] if sched.get("burst") else [])
    keep = {c["frames"][0] for c in sched["chains"][:keep_chains]}
    if sched.get("burst"):
        keep.add(sched["burst"]["frames"][0])
    removed = []
    for run in runs:
        for f in run["frames"]:
            if f in keep:
                continue
            for ch in channels:
                path = os.path.join(run_dir, "%s.%s.%d.exr" % (tag, ch, f))
                if os.path.isfile(path):
                    os.remove(path)
                    removed.append(path)
    return removed


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("tag")
    ap.add_argument("--keep-chains", type=int, default=2)
    a = ap.parse_args()
    print("pruned %d files from %s" % (len(prune(a.run_dir, a.tag, a.keep_chains)), a.run_dir))
