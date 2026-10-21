"""The paper's five-denoiser runs (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E3): the planned
captures in order (M cap 200 first), and whether one has finished.

    python five_runs.py --list [--sets "optix,oidn,relax,reblur"]   one capture a line: label config captures VAR=value...
    python five_runs.py --complete <run dir> <captures>             exit 0 if the run finished, 1 if not
"""
import argparse
import os
import sys

GALLERY_1 = ["bunnycathedral_d0.3", "bunnyspot", "bunnysoftbox", "bunnyinside", "bunnyback_g0.8", "bunnystripes",
             "explosion", "bunnylanterns", "wdassunset_g0.85", "plumeback_g0.9", "plumeconcert_g0.6", "emeraldnight_d3"]
GALLERY_2 = ["explosiondusk_b2", "bunnycathedral_d0.3_b2", "bunnyback_g0.8_b2", "bunnysoftbox_b2", "wdassunset_g0.85_b2"]
SMALL = ["bunnyswarm_d3", "wdasstorm_g0.5"]  # their references are 960x540
SETUPS = GALLERY_1 + GALLERY_2 + SMALL
HISTORIES = ("c200", "ship")
FOUR = "optix,oidn,relax,reblur"
ONE_BOUNCE = "light,depth,select,flight"
TWO_BOUNCE = ONE_BOUNCE + ",direction,distance,rebounce"
LOOK = ["VR_NRD_SPLIT=1", "VR_NRD_SH=1", "VR_NRD_TAA=1", "VR_TAA_LDR=1", "VR_NRD_EMISSION=1", "VR_NRD_VOLMASK=1",
        "VR_VOL_NORMAL=gradient"]  # run_study.sh's LOOK


def scene_env(label):
    """run_study.sh's scene_env: VR_SCENE, then VR_PHASE_G for _g<g>, VR_DENSITY_MULT for _d<m>, VR_MAX_BOUNCES for _b<n>."""
    scene, *mods = label.split("_")
    out = ["VR_SCENE=" + scene]
    for m in mods:
        key = {"g": "VR_PHASE_G", "d": "VR_DENSITY_MULT", "b": "VR_MAX_BOUNCES"}.get(m[:1])
        if key:
            out.append("%s=%s" % (key, m[1:]))
    return out


def runs(sets=(FOUR,)):
    """Every planned capture, in order: dicts with label, config, captures (EXR files when finished) and env."""
    out = []
    for hist in HISTORIES:
        for label in SETUPS:
            base = (scene_env(label) + LOOK
                    + ["VR_DISPLAY=" + ("960x540" if label in SMALL else "1920x1080"), "VR_CHAINS=2", "VR_PER_CHAIN=1",
                       "VR_SPACING=5", "VR_IDS=0"]
                    + (["VR_MTHRESH=200"] if hist == "c200" else []))
            for m in (0, 5):
                env = base + ([] if m == 0 else [
                    "VR_MUTATIONS=5", "VR_MUT_AFTER_SPATIAL=1",
                    "VR_MUT_STRAT=" + (TWO_BOUNCE if label.endswith("_b2") else ONE_BOUNCE)])
                for i, s in enumerate(sets):
                    name = "fd" if len(sets) == 1 else "fd%d" % (i + 1)
                    out.append({"label": label, "config": "%s_%s_m%d" % (name, hist, m),
                                "captures": 2 * (len(s.split(",")) + 1), "env": env + ["VR_DENOISERS=" + s]})
                out.append({"label": label, "config": "fr_%s_m%d" % (hist, m), "captures": 2,
                            "env": env + ["VR_DENOISER=rr"]})
    return out


def complete(run_dir, captures):
    """Finished: a schedule, a run log with no Falcor error, and exactly `captures` EXRs."""
    log = os.path.join(run_dir, "run.log")
    if not (os.path.isfile(os.path.join(run_dir, "c.schedule.json")) and os.path.isfile(log)):
        return False
    with open(log, errors="replace") as fh:
        if "(Error)" in fh.read():
            return False
    return len([f for f in os.listdir(run_dir) if f.startswith("c.") and f.endswith(".exr")]) == captures


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--sets", default=FOUR, help="denoiser sets, space-separated, one graph each")
    ap.add_argument("--complete", nargs=2, metavar=("RUN_DIR", "CAPTURES"))
    a = ap.parse_args(argv)
    if a.complete:
        return 0 if complete(a.complete[0], int(a.complete[1])) else 1
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(newline="\n")  # bash's `read` would keep Windows' \r in the last VAR=value
    for r in runs(tuple(a.sets.split())):
        print(r["label"], r["config"], r["captures"], " ".join(r["env"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
