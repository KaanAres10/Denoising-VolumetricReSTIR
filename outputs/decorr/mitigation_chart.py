"""What 5 mutations remove, scene by scene: the medium's neighbour correlation rho(8) (luminance blotches) and the
colour correlation (colour blotches), each without and with the mutations at the same M cap. One dumbbell per scene.

    python mitigation_chart.py outputs/decorr [--out figs/mitigation_chart.png]
"""
import argparse
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from atlas_figure import SCENES, resolve

BLUE, ORANGE = "#2a78d6", "#eb6834"  # reference palette slots 1 and 2
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
# (panel title, config without mutations, configs with them -- the first one run wins)
# Mutations alone: plain ReSTIR vs the same with 5 moves (newest first: all four kinds with the weighted
# re-selection, then all four, then older sets), no decoupled history.
PANELS = [("as shipped", "shipped", "mut5_all4w_post|mut5_all4_post|mut5_all|mut5_select_post"),
          ("M cap 50", "mcap_50", "mcap_50_mut5_all4w_post|mcap_50_mut5_all4_post|mcap_50_mut5_all_post|mcap_50_mut5_all|mcap_50_mut5"),
          ("M cap 200", "mcap_200", "mcap_200_mut5_all4w_post|mcap_200_mut5_all4_post")]
METRICS = [("luminance blotches, rho(8)", lambda c: (c.get("medium") or c["robust"])["rho"]["8"]),
           ("colour blotches, colour rho(8)", lambda c: c.get("color_rb", {}).get("rho", {}).get("8"))]


def pairs(root, without, with_spec, metric):
    out = []
    for label in SCENES:
        a, b = resolve(root, label, without), resolve(root, label, with_spec)
        if a is None or b is None:
            continue
        va, vb = (metric(json.load(open(os.path.join(root, label, c, "c.corr.json")))) for c in (a, b))
        if va is None or vb is None or va < 1e-3:  # below 0.001: no artifact to remove (noise)
            continue
        out.append((SCENES[label], va, vb))
    return sorted(out, key=lambda r: r[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--out")
    a = ap.parse_args()
    fig, ax = plt.subplots(len(METRICS), len(PANELS), figsize=(19, 10), squeeze=False, facecolor="#fcfcfb")
    for i, (mtitle, metric) in enumerate(METRICS):
        for j, (ptitle, without, with_spec) in enumerate(PANELS):
            x = ax[i][j]
            x.set_facecolor("#fcfcfb")
            rows = pairs(a.root, without, with_spec, metric)
            for k, (name, va, vb) in enumerate(rows):
                x.plot([va, vb], [k, k], color=GRID, lw=3, zorder=1, solid_capstyle="round")
                x.scatter([va], [k], s=70, color=BLUE, zorder=2, edgecolor="#fcfcfb", linewidth=2)
                x.scatter([vb], [k], s=70, color=ORANGE, zorder=3, edgecolor="#fcfcfb", linewidth=2)
                x.text(max(va, vb), k, "  %+.0f%%" % (100 * (vb / va - 1)), va="center", fontsize=9, color=MUTED)
            x.set_yticks(range(len(rows)))
            x.set_yticklabels([r[0] for r in rows], fontsize=9, color=INK)
            x.set_xlim(0, 1.25 * max((max(r[1], r[2]) for r in rows), default=1))
            x.set_title("%s -- %s" % (ptitle, mtitle), fontsize=10, color=INK, loc="left")
            x.grid(axis="x", color=GRID, lw=0.8)
            x.set_axisbelow(True)
            for s in ("top", "right", "left"):
                x.spines[s].set_visible(False)
            x.spines["bottom"].set_color(MUTED)
            x.tick_params(axis="x", colors=MUTED, labelsize=8)
            x.tick_params(axis="y", length=0)
    handles = [plt.Line2D([], [], marker="o", ls="", color=c, markersize=8, label=l)
               for c, l in ((BLUE, "without mutations"), (ORANGE, "+ 5 mutations"))]
    fig.legend(handles=handles, loc="upper right", frameon=False, fontsize=10, ncol=2)
    fig.suptitle("What 5 Metropolis-Hastings mutations remove (lower = less correlated; 100 frames per point)",
                 fontsize=12, x=0.01, ha="left", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out = a.out or os.path.join(a.root, "figs", "mitigation_chart.png")
    fig.savefig(out, dpi=110, facecolor=fig.get_facecolor())
    print(out)


if __name__ == "__main__":
    main()
