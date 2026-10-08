"""run_bias_final.sh's verdict: per setup, the mutated pass's image mean against plain ReSTIR's (paired chains, as
bias_check.py --paired), per channel and in luminance, in percent and in standard errors; then the luminance z of all
setups together: under "the mutations change no expectation" each z is a standard normal draw, so their sum of squares
is chi-square with one degree of freedom per setup.

    python bias_summary.py <outputs/decorr/biasfinal>
"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bias_check

Y_RGB = np.array([0.2126, 0.7152, 0.0722])  # Rec. 709


def luminance(rgb):
    return np.asarray(rgb, dtype=np.float64) @ Y_RGB


def setup_z(means, base="plain", conf="mut5"):
    """{"rgb": (bias, se, z) per channel, "lum": (bias, se, z)} from a chains.json's chain means."""
    b, c = np.asarray(means[base], dtype=np.float64), np.asarray(means[conf], dtype=np.float64)
    bias, se = bias_check.paired_relative_bias(c, b)
    lb, ls = bias_check.paired_relative_bias(luminance(c)[:, None], luminance(b)[:, None])
    z = lambda m, s: np.where(s > 0, m / np.where(s > 0, s, 1.0), np.where(m == 0, 0.0, np.inf))
    return {"rgb": (bias, se, z(bias, se)), "lum": (float(lb[0]), float(ls[0]), float(z(lb, ls)[0]))}


def chi2_sf(x, dof):
    """P(chi-square_dof >= x) for an even dof: exp(-x/2) * sum_{i<dof/2} (x/2)^i / i!."""
    if dof % 2:
        raise ValueError("even degrees of freedom only")
    h = x / 2.0
    return math.exp(-h) * sum(h ** i / math.factorial(i) for i in range(dof // 2))


def rows(root):
    out = []
    for label in sorted(os.listdir(root)):
        p = os.path.join(root, label, "chains.json")
        if os.path.exists(p):
            with open(p) as fh:
                out.append((label, setup_z(json.load(fh))))
    return out


def main(argv):
    r = rows(argv[1])
    print("%-24s %32s %32s" % ("setup", "R / G / B bias % (z)", "luminance bias % +- s.e. (z)"))
    for label, z in r:
        bias, se, zz = z["rgb"]
        lb, ls, lz = z["lum"]
        print("%-24s %32s %32s" % (label, " ".join("%+.2f(%+.1f)" % (100 * a, b) for a, b in zip(bias, zz)),
                                     "%+.2f%% +- %.2f%% (%+.2f)" % (100 * lb, 100 * ls, lz)))
    zs = [z["lum"][2] for _, z in r]
    if zs:
        x = float(np.sum(np.square(zs)))
        dof = len(zs) + (len(zs) % 2)  # (an odd count is padded with a zero term: conservative)
        print("luminance: max |z| %.2f; %d of %d beyond 2; chi-square %.2f on %d setups, p = %.3f"
              % (max(abs(v) for v in zs), sum(abs(v) > 2 for v in zs), len(zs), x, len(zs), chi2_sf(x, dof)))


if __name__ == "__main__":
    main(sys.argv)
