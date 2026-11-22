"""The space-time strips, (x, t) plots after Junkins et al. (2026, Fig. 5), for three of the paper's setups: each of a
setup's five-denoiser runs is rendered again from the environment its schedule recorded, its second chain carried on
for STRIP_FRAMES frames, keeping a 32-row band of every channel (correlation_pose.py's VR_STRIP_*). The strip's first
frame is that run's captured frame 1602, byte for byte.

The band lies inside the setup's figure box (five_figures.panel), where plain ReSTIR with OptiX errs most on chain 0,
the paper crops' chain, so the strips (chain 1) are not chosen on their own noise.

With --night, the night street's M cap 50 runs instead, plain and with five mutations (user-asked 2026-11-01, after
the viewer's view of them through DLSS RR): its band, by the same rule at M cap 50 against the 524k-spp reference,
lies inside that view (x 861-1281, y 452-694 of the frame).

    python spacetime_runs.py --list [root] [--night]   one run a line: label config VAR=value ...
    python spacetime_runs.py --complete <run dir>      exit 0 if the run left every strip
"""
import argparse
import json
import os
import re
import sys

SCENES = {"bunnyswarm_d3": (196, 228), "bunnylanterns": (208, 240), "wdassunset_g0.85": (643, 675)}
NIGHT = {"emeraldnight_d3": (584, 616)}
STRIP_FRAMES = 128
SOURCE = re.compile(r"^(fd\d?|fr)_(c200|ship)_m[05]$")  # the paper's runs (five_runs.py), not their replays
NIGHT_SOURCE = re.compile(r"^(fd\d?|fr)_c50_m[05]$")  # the cap sweep's, not the one-off mutation counts or shaders


def runs(root, scenes=SCENES, frames=STRIP_FRAMES, source=SOURCE):
    """One replay per run of each setup that `source` matches (the paper's): label, config st_<run> and the run's own
    environment, less its output folder and tag, plus the strip's."""
    out = []
    for label, (y0, y1) in scenes.items():
        for cfg in sorted(os.listdir(os.path.join(root, label))):
            if not source.match(cfg):
                continue
            with open(os.path.join(root, label, cfg, "c.schedule.json")) as fh:
                env = {k: v for k, v in json.load(fh)["env"].items() if k not in ("VR_OUT_DIR", "VR_TAG")}
            env.update({"VR_STRIP_FRAMES": str(frames), "VR_STRIP_ROWS": "%d:%d" % (y0, y1)})
            out.append({"label": label, "config": "st_" + cfg, "env": env})
    return out


def complete(run_dir):
    """Finished: a schedule naming a strip, a run log with no Falcor error, and every channel's strip."""
    sched, log = os.path.join(run_dir, "c.schedule.json"), os.path.join(run_dir, "run.log")
    if not (os.path.exists(sched) and os.path.exists(log)):
        return False
    with open(log, errors="replace") as fh:
        if re.search(r"\((Error|Fatal)\)", fh.read()):
            return False
    with open(sched) as fh:
        strip = json.load(fh).get("strip")
    return bool(strip) and all(os.path.exists(os.path.join(run_dir, "c.strip.%s.npy" % name))
                               for name in strip["channels"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", nargs="?", const=os.path.dirname(os.path.abspath(__file__)), metavar="ROOT")
    ap.add_argument("--complete", metavar="RUN_DIR")
    ap.add_argument("--night", action="store_true")
    a = ap.parse_args()
    if a.complete:
        sys.exit(0 if complete(a.complete) else 1)
    sys.stdout.reconfigure(newline="\n")  # Windows writes \r\n, and bash's read keeps the \r on each line's last value
    for r in (runs(a.list, scenes=NIGHT, source=NIGHT_SOURCE) if a.night else runs(a.list)):
        print(r["label"], r["config"], " ".join("%s=%s" % kv for kv in sorted(r["env"].items())))
