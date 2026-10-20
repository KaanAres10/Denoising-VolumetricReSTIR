"""How far each re-rendered reference moved (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E2):
<label>/ref (rendered after a2a3aa8) against <label>/ref_residual (before it), in the label's medium
(noreuse/c.medium.npy).

    python ref_change.py <root> <label> [<label> ...] [--out F]

Per label: the new reference's mean luminance over the old one's, the relMSE of the old against the new, and each
one's own relMSE (two independent references differ by about the sum of their own errors when nothing changed).
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import medium_metrics as mm  # noqa: E402


def change(root, label):
    mask = np.load(os.path.join(root, label, "noreuse", "c.medium.npy"))
    new = mm.accumulations(os.path.join(root, label, "ref"))
    old = mm.accumulations(os.path.join(root, label, "ref_residual"))
    return {"mean_ratio": mm.brightness(new[-1], old[-1], mask),
            "relmse_old_vs_new": mm.relmse(old[-1], new[-1], mask),
            "own_relmse_new": mm.relmse(new[-2], new[-1], mask),
            "own_relmse_old": mm.relmse(old[-2], old[-1], mask)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("labels", nargs="+")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    out = {label: change(a.root, label) for label in a.labels}
    for label, c in out.items():
        print("%-24s new/old mean %.4f  relMSE old vs new %.5f  own: new %.5f old %.5f"
              % (label, c["mean_ratio"], c["relmse_old_vs_new"], c["own_relmse_new"], c["own_relmse_old"]))
    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, "w") as fh:
            json.dump(out, fh, indent=1)
    return out


if __name__ == "__main__":
    main()
