"""run_speed_ab.sh's verdict: per scene setup, whether the two shader versions render the same frames bit for bit
(A1 vs A2 first: the renderer must repeat itself, or A vs B means nothing), and the GPU time of each (the mean of its
two runs' medians: whole VolumetricReSTIR pass and Mutate Samples alone).

    python speed_ab_check.py <outputs/decorr/speed_ab/<name>> [--against <outputs/decorr/speed_ab/<other>>]

--against: each scene's A1 here vs B1 there, bit for bit (stage 2 with its switch off must render stage 1's frames).
"""
import glob
import json
import os
import re
import sys

import numpy as np

LANE = "/onFrameRender/RenderGraphExe::execute()/VolumetricReSTIR"
CHANNEL = "c.VolumetricReSTIR.accumulated_color"


def _frames(run_dir, ext):
    out = {}
    for p in glob.glob(os.path.join(run_dir, CHANNEL + ".*" + ext)):
        m = re.search(r"\.(\d+)" + re.escape(ext) + "$", p)
        if m:
            out[int(m.group(1))] = p
    return out


def _read_exr(path):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import m_corr
    return m_corr.read_exr(path)


def compare(a_dir, b_dir, ext=".exr", load=_read_exr):
    """Frame by frame: identical (every value equal, NaN where the other has NaN), how many pixels differ, the largest
    difference among finite values, and frames present on one side only."""
    fa, fb = _frames(a_dir, ext), _frames(b_dir, ext)
    out = {"frames": len(set(fa) | set(fb)), "identical": 0, "pixels_differ": 0, "max_abs": 0.0,
           "missing": len(set(fa) ^ set(fb))}
    for f in sorted(set(fa) & set(fb)):
        a, b = np.asarray(load(fa[f])), np.asarray(load(fb[f]))
        if a.shape != b.shape:
            out["pixels_differ"] += a.shape[0] * a.shape[1]
            continue
        same = (a == b) | (np.isnan(a) & np.isnan(b))
        bad = ~same.reshape(a.shape[0], a.shape[1], -1).all(axis=2)
        if not bad.any():
            out["identical"] += 1
            continue
        out["pixels_differ"] += int(bad.sum())
        d = np.abs(a.astype(np.float64) - b.astype(np.float64))
        d = d[np.isfinite(d)]
        out["max_abs"] = max(out["max_abs"], float(d.max()) if d.size else float("inf"))
    return out


def _lane(run_dir, name=""):
    with open(os.path.join(run_dir, "c.passes.json")) as fh:
        d = json.load(fh)
    return d.get(LANE + ("/" + name if name else "") + "/gpu_time", {}).get("median", 0.0)


def times(label_dir):
    """{variant: {"total": ms, "mutate": ms}}: the mean over that variant's runs (A1, A2 / B1, B2) on disk."""
    out = {}
    for v in ("A", "B"):
        runs = [os.path.join(label_dir, v + n) for n in ("1", "2")]
        runs = [r for r in runs if os.path.exists(os.path.join(r, "c.passes.json"))]
        if runs:
            out[v] = {"total": float(np.mean([_lane(r) for r in runs])),
                      "mutate": float(np.mean([_lane(r, "Mutate Samples") for r in runs]))}
    return out


def against(root, other, ext=".exr", load=_read_exr):
    """{scene: compare(root/scene/A1, other/scene/B1)} for the scenes both have."""
    out = {}
    for label in sorted(os.listdir(root)):
        a, b = os.path.join(root, label, "A1"), os.path.join(other, label, "B1")
        if os.path.isdir(a) and os.path.isdir(b):
            out[label] = compare(a, b, ext=ext, load=load)
    return out


def main(argv):
    root = argv[1]
    if "--against" in argv:
        other = argv[argv.index("--against") + 1]
        for label, c in against(root, other).items():
            print("%-24s A1 vs %s B1: %d/%d frames identical, %d pixels differ, max %.3g, %d missing"
                  % (label, os.path.basename(other.rstrip("/")), c["identical"], c["frames"], c["pixels_differ"],
                     c["max_abs"], c["missing"]))
        return
    fmt = "%-24s %-13s %-13s %9s %9s %8s %10s %10s %8s"
    print(fmt % ("scene", "A1 vs A2", "A1 vs B1", "A total", "B total", "change", "A mutate", "B mutate", "change"))
    for label in sorted(os.listdir(root)):
        d = os.path.join(root, label)
        if not os.path.isdir(d):
            continue
        same = lambda x, y: (lambda c: "%d/%d same" % (c["identical"], c["frames"]) if not c["missing"]
                             else "%d missing" % c["missing"])(compare(os.path.join(d, x), os.path.join(d, y)))
        t = times(d)
        if "A" not in t or "B" not in t:
            print("%-24s incomplete" % label)
            continue
        a, b = t["A"], t["B"]
        print(fmt % (label, same("A1", "A2"), same("A1", "B1"), "%.1f" % a["total"], "%.1f" % b["total"],
                     "%+.0f%%" % (100 * (b["total"] / a["total"] - 1)), "%.1f" % a["mutate"], "%.1f" % b["mutate"],
                     "%+.0f%%" % (100 * (b["mutate"] / a["mutate"] - 1)) if a["mutate"] else "-"))


if __name__ == "__main__":
    main(sys.argv)
