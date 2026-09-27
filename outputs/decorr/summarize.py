"""One row per scored correlation run: <root>/<scene label>/<config>/c.corr.json -> <root>/summary.tsv.

    python summarize.py [outputs/decorr]
"""
import glob
import json
import os
import sys

COLUMNS = ["label", "config", "K", "mean",
           "rho_raw_r1", "rho_raw_r8", "rho_robust_r1", "rho_robust_r4", "rho_robust_r8",
           "rho_robust_r8_lo", "rho_robust_r8_hi", "delta_robust_r8", "delta_robust_r8_lo", "delta_robust_r8_hi",
           "corr_len", "top_offset", "dup_sample", "dup_light", "temporal_lag", "relmse", "blur_rms_8", "bias_whole"]


def _get(d, *keys):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return ""
        d = d[k]
    return d


def row(label, config, r):
    top = _get(r, "autocorr", "top_offsets")
    return {
        "label": label, "config": config, "K": r.get("K", ""), "mean": r.get("mean_level", ""),
        "rho_raw_r1": _get(r, "raw", "rho", "1"), "rho_raw_r8": _get(r, "raw", "rho", "8"),
        "rho_robust_r1": _get(r, "robust", "rho", "1"), "rho_robust_r4": _get(r, "robust", "rho", "4"),
        "rho_robust_r8": _get(r, "robust", "rho", "8"),
        "rho_robust_r8_lo": (_get(r, "robust", "ci", "8") or ["", ""])[0],
        "rho_robust_r8_hi": (_get(r, "robust", "ci", "8") or ["", ""])[1],
        "delta_robust_r8": _get(r, "delta", "robust", "8", "value"),
        "delta_robust_r8_lo": (_get(r, "delta", "robust", "8", "ci") or ["", ""])[0],
        "delta_robust_r8_hi": (_get(r, "delta", "robust", "8", "ci") or ["", ""])[1],
        "corr_len": _get(r, "autocorr", "length_0.1"),
        "top_offset": "%d,%d:%.3f" % tuple(top[0]) if top else "",
        "dup_sample": _get(r, "duplicates", "sample_mean"), "dup_light": _get(r, "duplicates", "light_mean"),
        "temporal_lag": _get(r, "temporal", "lag_below_0.05"),
        "relmse": _get(r, "reference", "relmse"), "blur_rms_8": _get(r, "reference", "blur_rms", "8"),
        "bias_whole": _get(r, "reference", "regions", "whole", "bias"),
    }


def summarize(root):
    rows = []
    for path in sorted(glob.glob(os.path.join(root, "*", "*", "c.corr.json"))):
        config_dir = os.path.dirname(path)
        with open(path) as fh:
            r = json.load(fh)
        rows.append(row(os.path.basename(os.path.dirname(config_dir)), os.path.basename(config_dir), r))
    fmt = lambda v: ("%.6g" % v) if isinstance(v, float) else str(v)
    with open(os.path.join(root, "summary.tsv"), "w") as fh:
        fh.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            fh.write("\t".join(fmt(r[c]) for c in COLUMNS) + "\n")
    return rows


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    print("%d runs -> %s" % (len(summarize(root)), os.path.join(root, "summary.tsv")))
