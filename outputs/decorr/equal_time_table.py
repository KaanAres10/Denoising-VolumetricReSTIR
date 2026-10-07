"""Equal time (run_equal_time.sh): per scene, the denoised error of plain ReSTIR, ReSTIR + 5 mutations, and plain ReSTIR
with the initial candidates that cost what the 5 mutations cost -- all through OptiX at M cap 200. The error is
variety_figures.py's (relMSE in the medium, clipped at its brightest 0.5%), averaged over the kept frames (the first
frame of chains 0 and 1); rho(8) is m_corr's over every frame of the run.

    python equal_time_table.py <root>        (root: outputs/decorr)
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art
import paper_figure

LABELS = ["explosiondusk", "bunnycathedral_d0.3", "bunnyback_g0.8", "bunnysoftbox", "wdassunset_g0.85"]
CONFIGS = ("den_optix_mut0cap200", "den_optix_mut5cap200", "den_optix_eq5cap200")


def scores(root, label):
    """{config: (relMSE in the medium, mean over kept frames; rho(8); initial candidates)} for the configs on disk."""
    if not all(os.path.exists(os.path.join(root, label, c, "c.corr.json")) for c in CONFIGS[:2]):
        return None
    p = paper_figure.prepare(root, label, CONFIGS[0], CONFIGS[1])
    out = {}
    for c in CONFIGS:
        d = os.path.join(root, label, c)
        if not os.path.exists(os.path.join(d, "c.corr.json")):
            continue
        with open(os.path.join(d, "c.corr.json")) as fh:
            corr = json.load(fh)
        frames = art.kept_all(d)
        rel = float(np.mean([p.relmse(f[p.crop]) for f in frames]))
        out[c] = (rel, corr["raw"]["rho"]["8"], int(corr["env"].get("VR_INITIAL_M", 4)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    a = ap.parse_args(argv)
    fmt = "%-24s %15s %22s %26s"
    print(fmt % ("scene", "plain (4 cand.)", "+ 5 mutations", "plain, equal time"))
    for base in LABELS:
        for label in (base, base + "_b2"):
            s = scores(a.root, label)
            if not s:
                continue
            r0 = s[CONFIGS[0]][0]
            cell = lambda c: ("%.4f (%+.0f%%)" % (s[c][0], 100 * (s[c][0] / r0 - 1))) if c in s else "-"
            eq = cell(CONFIGS[2]) + (" [%d cand.]" % s[CONFIGS[2]][2] if CONFIGS[2] in s else "")
            print(fmt % (label, "%.4f" % r0, cell(CONFIGS[1]), eq))


if __name__ == "__main__":
    main()
