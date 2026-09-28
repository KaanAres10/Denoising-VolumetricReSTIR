"""Why M cap 50: error and correlation against the temporal M cap, with 0 / 1 / 5 mutations, per deep scene.

    python mcap_chart.py outputs/decorr   -> outputs/decorr/mcap_chart.png
"""
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
# The reference palette's first three categorical slots, fixed order; marker shape is the secondary encoding.
SERIES = [("no mutation", "#2a78d6", "o"), ("1 mutation", "#eb6834", "s"), ("5 mutations", "#1baf7a", "^")]
SCENES = {
    "plume_g-0.9": ("plume g = -0.9 (smoke)", 4, [
        {"mcap_1": 1, "shipped": 4, "mcap_10": 10, "mcap_20": 20, "mcap_50": 50, "mcap_200": 200},
        {"mut1_both": 4, "mcap_10_mut1": 10, "mcap_50_mut1": 50, "mcap_200_mut1": 200},
        {"mut5_both": 4, "mcap_50_mut5": 50}]),
    "emerald": ("Emerald Square (fog)", 10, [
        {"mcap_1": 1, "mcap_4": 4, "shipped": 10, "mcap_20": 20, "mcap_50": 50, "mcap_200": 200},
        {"mut1_both": 10, "mcap_50_mut1": 50, "mcap_200_mut1": 200},
        {"mut5_both": 10, "mcap_50_mut5": 50}]),
    "bistro": ("Bistro (whole image)", 10, [
        {"mcap_1": 1, "mcap_4": 4, "shipped": 10, "mcap_20": 20, "mcap_50": 50, "mcap_200": 200},
        {"mut1_both": 10, "mcap_50_mut1": 50, "mcap_200_mut1": 200},
        {"mut5_both": 10}]),
}


def point(label, cfg):
    j = json.load(open(os.path.join(ROOT, label, cfg, "c.corr.json")))
    block = j["robust"] if label == "bistro" else j.get("medium", j["robust"])
    return j["reference"]["relmse"], block["rho"]["8"]


fig, ax = plt.subplots(2, 3, figsize=(15, 8.5))
for col, (label, (title, shipped, runs)) in enumerate(SCENES.items()):
    for (name, color, marker), cfgs in zip(SERIES, runs):
        pts = sorted((cap, *point(label, cfg)) for cfg, cap in cfgs.items())
        caps = [p[0] for p in pts]
        for row in (0, 1):
            ax[row, col].plot(caps, [p[1 + row] for p in pts], "-", marker=marker, color=color, lw=2, ms=8,
                              markeredgecolor="white", markeredgewidth=1.5, label=name)
    for row, ylabel in ((0, "relMSE vs reference (lower is better)"), (1, "neighbour correlation rho(8) (lower is better)")):
        a = ax[row, col]
        a.set_xscale("log", base=2)
        a.set_xticks([1, 4, 10, 20, 50, 200])
        a.set_xticklabels(["1", "4", "10", "20", "50", "200"])
        a.axvline(shipped, color="#888888", lw=1, ls=":")
        a.axvline(50, color="#444444", lw=1, ls="--")
        a.grid(True, color="#e6e6e6", lw=0.8)
        a.set_axisbelow(True)
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
        if row == 0:
            a.set_yscale("log")
            a.set_title(title, fontsize=13)
        a.set_xlabel("temporal M cap" if row == 1 else "")
        if col == 0:
            a.set_ylabel(ylabel)
    ax[0, col].text(shipped, ax[0, col].get_ylim()[1], " shipped", color="#666666", fontsize=9, va="top")
    ax[0, col].text(50, ax[0, col].get_ylim()[1], " 50", color="#333333", fontsize=9, va="top")
ax[1, 0].legend(frameon=False, fontsize=10, loc="upper left")
fig.suptitle("Why M cap 50: error falls steeply up to ~50 and then flattens (or rises); correlation keeps rising, "
             "and mutations take it back", fontsize=13)
fig.tight_layout(rect=(0, 0, 1, 0.95))
out = os.path.join(ROOT, "mcap_chart.png")
fig.savefig(out, dpi=80)
print(out)
