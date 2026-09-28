"""Error against correlation, per scene: ReSTIR's trade-off (Junkins et al. 2026, Sec. 6). The M cap and the reuse
radius move a configuration along one curve; a technique helps only if it moves the curve toward the lower left.

    python pareto_chart.py outputs/decorr   -> outputs/decorr/pareto_chart.png

x = relMSE against the path-traced reference (lower is better), y = mean neighbour correlation rho(8) in the
medium (lower is better). Series without runs on disk are skipped.
"""
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
# The reference palette's categorical slots in fixed order; the marker shape is the secondary encoding.
SERIES = [
    ("M cap sweep, no mutation", "#2a78d6", "o", {"mcap_1": 1, "mcap_4": 4, "shipped": None, "mcap_10": 10,
                                                   "mcap_20": 20, "mcap_50": 50, "mcap_200": 200}),
    ("+ 1 mutation", "#eb6834", "s", {"mut1_both": None, "mcap_10_mut1": 10, "mcap_50_mut1": 50, "mcap_200_mut1": 200}),
    ("+ 5 mutations", "#1baf7a", "^", {"mut5_both": None, "mcap_50_mut5": 50}),
    ("decoupled history", "#eda100", "D", {"dec": None, "dec_mcap_50": 50, "dec_mcap_200": 200}),
    ("decoupled + 5 mutations", "#e87ba4", "v", {"dec_mcap_50_mut5": 50}),
    ("duplication M cap (0.5)", "#008300", "P", {"mcap_50_dup05": 50, "mcap_200_dup05": 200}),
    ("duplication cap + 5 mutations", "#4a3aa7", "X", {"mcap_50_dup05_mut5": 50}),
    ("reuse radius 3 / 30 (+5 = 5 mutations)", "#e34948", "*", {"radius_3": "r3", "radius_30": "r30", "mcap_50_r30": "r30 cap 50",
                                            "mcap_50_r30_mut5": "r30 cap 50 +5"}),
]
MARKS = {"spatial_only": "spatial only", "temporal_only": "temporal only"}
SCENES = {"plume_g-0.9": ("plume g = -0.9 (smoke)", 4), "emerald": ("Emerald Square (fog)", 10)}


def point(label, cfg):
    p = os.path.join(ROOT, label, cfg, "c.corr.json")
    if not os.path.exists(p):
        return None
    j = json.load(open(p))
    if "reference" not in j:
        return None
    return j["reference"]["relmse"], (j.get("medium") or j["robust"])["rho"]["8"]


fig, axes = plt.subplots(1, len(SCENES), figsize=(8 * len(SCENES), 7))
for ax, (label, (title, shipped)) in zip(axes, SCENES.items()):
    for name, color, marker, cfgs in SERIES:
        pts = []
        for cfg, tag in cfgs.items():
            xy = point(label, cfg)
            if xy:
                pts.append((xy[0], xy[1], shipped if tag is None else tag))
        if not pts:
            continue
        joined = all(isinstance(p[2], int) for p in pts)
        if joined:
            pts.sort(key=lambda p: p[2])  # along the M cap, not along the error
        ax.plot([p[0] for p in pts], [p[1] for p in pts], linestyle="-" if joined else "none", marker=marker,
                color=color, lw=2, ms=15 if marker == "*" else 9, markeredgecolor="white", markeredgewidth=1.2, label=name)
        for x, y, tag in pts:
            ax.annotate(str(tag), (x, y), textcoords="offset points", xytext=(6, 4), fontsize=8, color="#444444")
    floor = 1.5e-3  # temporal-only reuse correlates almost nothing: pinned to the axis floor, marked as below it
    for cfg, text in MARKS.items():
        xy = point(label, cfg)
        if xy:
            below = xy[1] < floor
            y = floor * 1.08 if below else xy[1]
            ax.plot(xy[0], y, "v" if below else "o", color="#888888", ms=8)
            ax.annotate(text + (" (rho %.4f)" % xy[1] if below else ""), (xy[0], y), textcoords="offset points",
                        xytext=(6, 4), fontsize=8, color="#666666")
    xy = point(label, "shipped")
    if xy:
        ax.plot(*xy, "o", ms=16, mfc="none", mec="#222222", mew=1.5)
        ax.annotate("as shipped", xy, textcoords="offset points", xytext=(10, 10), fontsize=9, color="#222222")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_ylim(bottom=floor)
    ax.set_xlabel("relMSE vs path-traced reference (lower is better)")
    ax.set_ylabel("neighbour correlation rho(8) in the medium (lower is better)")
    ax.set_title(title + "  (numbers = M cap)", fontsize=13)
    ax.grid(True, which="both", color="#eeeeee", lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
axes[0].legend(frameon=False, fontsize=9, loc="upper right")
fig.suptitle("Error vs correlation (lower-left is better): keeping spatial reuse out of the history moves the whole "
             "curve down; mutations help at long history and wide radius", fontsize=13)
fig.tight_layout(rect=(0, 0, 1, 0.95))
out = os.path.join(ROOT, "pareto_chart.png")
fig.savefig(out, dpi=80)
print(out)
