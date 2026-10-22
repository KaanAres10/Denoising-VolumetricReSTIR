"""The moving-camera test with all seven moves (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E7):
cam_pose.py's captures of the construct, scored against the still shot's reference in its medium, plain vs 5
mutations per output (OptiX, RR, raw).

    python motion_score.py [<run root>] [--out five_denoisers/motion.json]
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art  # noqa: E402
import five_scores  # noqa: E402
import medium_metrics as mm  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "previews", "glowcam")
LABEL = "lanternglow_b2"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=ROOT)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "five_denoisers", "motion.json"))
    a = ap.parse_args(argv)
    ref = art.reference(a.root, LABEL)
    mask = np.load(os.path.join(a.root, LABEL, "noreuse", "c.medium.npy"))
    out = {}
    for name in ("optix", "rr", "raw"):
        vals = {}
        for m in (0, 5):
            run = os.path.join(a.root, LABEL, "cam7_%s_m%d" % (name, m))
            img = five_scores.frames(run, five_scores.schedule(run)["channel"])[0]
            vals["m%d" % m] = mm.relmse(img, ref, mask)
            vals["brightness_m%d" % m] = mm.brightness(img, ref, mask)
        vals["change"] = vals["m5"] / vals["m0"] - 1
        out[name] = vals
        print("%-5s relMSE %.5f -> %.5f (%+.0f%%), brightness %.3f / %.3f"
              % (name, vals["m0"], vals["m5"], 100 * vals["change"], vals["brightness_m0"], vals["brightness_m5"]))
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1)
    return out


if __name__ == "__main__":
    main()
