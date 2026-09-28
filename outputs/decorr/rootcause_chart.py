"""Why more mutations stop helping (spec V-B7), plume g = -0.9, correlation in the smoke.

Left: rho(8) against mutations per pixel at the shipped M cap and at 50, with the level spatial reuse alone
reaches. Right: rho(8) against how many pixels share an exact sample: with mutations a frame shares fewer samples
than spatial-only reuse yet keeps 2.5x its correlation, so the samples are not what carries it.

    python rootcause_chart.py outputs/decorr   -> outputs/decorr/rootcause_chart.png
"""
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
LABEL = "plume_g-0.9"
CURVES = [("shipped M cap (4)", "#2a78d6", "o", {0: "shipped", 1: "mut1_depth", 5: "mut5_depth", 32: "mut32_depth"}),
          ("M cap 50", "#eb6834", "s", {0: "mcap_50", 1: "mcap_50_mut1_depth", 32: "mcap_50_mut32_depth"})]


def load(cfg):
    j = json.load(open(os.path.join(ROOT, LABEL, cfg, "c.corr.json")))
    return (j.get("medium") or j["robust"])["rho"]["8"], j["duplicates"]["sample_mean"]


fig, (a, b) = plt.subplots(1, 2, figsize=(15, 6))
floor = load("spatial_only")[0]
for name, color, marker, cfgs in CURVES:
    n = sorted(cfgs)
    a.plot([k + 0.5 for k in n], [load(cfgs[k])[0] for k in n], "-", marker=marker, color=color, lw=2, ms=9,
           markeredgecolor="white", markeredgewidth=1.2, label=name)
a.axhline(floor, color="#666666", ls="--", lw=1.2)
a.text(0.55, floor * 1.06, "spatial reuse alone (0 or 5 mutations: %.4f)" % floor, color="#444444", fontsize=9)
a.set_xscale("log")
a.set_xticks([0.5, 1.5, 5.5, 32.5])
a.set_xticklabels(["0", "1", "5", "32"])
a.set_xlabel("depth mutations per pixel per frame")
a.set_ylabel("neighbour correlation rho(8) in the smoke")
a.set_ylim(bottom=0)
a.set_title("Mutations saturate well above what spatial reuse alone gives", fontsize=12)
a.legend(frameon=False)

# (label, config, colour, marker, label offset in points)
pts = [("spatial only", "spatial_only", "#888888", "o", (7, 8)), ("shipped", "shipped", "#2a78d6", "o", (7, 4)),
       ("shipped + 5 / + 32", "mut32_depth", "#2a78d6", "D", (8, -3)),
       ("cap 50", "mcap_50", "#eb6834", "s", (-40, -14)), ("cap 50 + 5", "mcap_50_mut5", "#eb6834", "^", (-70, 4)),
       ("cap 50 + 32", "mcap_50_mut32_depth", "#eb6834", "D", (-75, -10)),
       ("decoupled history, no mutation", "dec", "#eda100", "P", (8, -12))]
for text, cfg, color, marker, off in pts:
    if not os.path.exists(os.path.join(ROOT, LABEL, cfg, "c.corr.json")):
        continue
    rho, dup = load(cfg)
    b.plot(dup, rho, marker, color=color, ms=10, markeredgecolor="white", markeredgewidth=1.2)
    b.annotate(text, (dup, rho), textcoords="offset points", xytext=off, fontsize=9, color="#333333")
b.set_xlabel("pixels per 20x20 tile holding a sample another pixel of the tile also holds")
b.set_ylabel("neighbour correlation rho(8) in the smoke")
b.set_ylim(bottom=0)
b.set_xlim(0, 32)
b.set_title("Same sample sharing, 3x the correlation: the history's shared normalization", fontsize=12)
for ax in (a, b):
    ax.grid(True, color="#eeeeee", lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
fig.suptitle("plume g = -0.9: what is left after mutations is the shared normalization (runningSum / M), "
             "which mutations keep by construction", fontsize=13)
fig.tight_layout(rect=(0, 0, 1, 0.94))
out = os.path.join(ROOT, "rootcause_chart.png")
fig.savefig(out, dpi=80)
print(out)
