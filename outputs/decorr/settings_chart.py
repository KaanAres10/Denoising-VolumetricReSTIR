"""After the same denoiser (OptiX), the error in the medium of plain ReSTIR and of ReSTIR + 5 mutations, at the
shipped M cap and at M cap 200, per showcase scene, relative to plain ReSTIR as shipped. Each value is the clipped
in-medium relMSE of paper_figure.prepare, averaged over the kept first frames of the independent chains.

    python settings_chart.py <root> [--out F]
"""
import argparse
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art
import paper_figure

BLUE, ORANGE = "#2a78d6", "#eb6834"  # reference palette slots 1 and 2
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
SCENES = {"bunnycathedral_d0.3": "Cathedral god rays", "bunnysoftbox": "Warm and cool panel lights",
          "bunnylanterns": "48 coloured lanterns", "wdassunset_g0.85": "Cloud at sunset",
          "plumeconcert_g0.6": "Concert beams in smoke"}
SETTINGS = [("shipped (M cap 4)", "den_optix_mut0ship", "den_optix_mut5ship"),
            ("M cap 200", "den_optix_mut0cap200", "den_optix_mut5cap200")]


def errors(root, label):
    """{setting: (plain, mutated)} in-medium relMSE, each the mean over the chains' kept frames."""
    out = {}
    for name, without, with_ in SETTINGS:
        p = paper_figure.prepare(root, label, without, with_)
        out[name] = tuple(float(np.mean([p.relmse(f[p.crop]) for f in art.kept_all(os.path.join(root, label, c))]))
                          for c in (without, with_))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rows = []
    for label in SCENES:
        e = errors(a.root, label)
        base = e[SETTINGS[0][0]][0]
        print("%-22s " % label + "  ".join("%s %.4f -> %.4f (%+.0f%%)" % (n, *e[n], 100 * (e[n][1] / e[n][0] - 1))
                                          for n, _, _ in SETTINGS))
        rows.append((SCENES[label], [(n, e[n][0] / base, e[n][1] / base) for n, _, _ in SETTINGS]))
    fig, ax = plt.subplots(figsize=(11, 0.5 * len(rows) * (len(SETTINGS) + 1) + 2.4), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    y, ticks, names = 0, [], []
    for scene, settings in reversed(rows):
        for name, va, vb in reversed(settings):
            ax.plot([va, vb], [y, y], color=GRID, lw=3, zorder=1, solid_capstyle="round")
            ax.scatter([va], [y], s=80, color=BLUE, zorder=2, edgecolor=SURFACE, linewidth=2)
            ax.scatter([vb], [y], s=80, color=ORANGE, zorder=3, edgecolor=SURFACE, linewidth=2)
            ax.text(max(va, vb) * 1.08, y, "%+.0f%%" % (100 * (vb / va - 1)), va="center", fontsize=10, color=MUTED)
            ticks.append(y)
            names.append(name)
            y += 1
        ax.text(0.0, y - 0.35, scene, transform=ax.get_yaxis_transform(), ha="right", fontsize=11, color=INK,
                fontweight="bold")
        y += 0.9
    ax.axvline(1, color=MUTED, lw=1, ls=(0, (4, 3)), zorder=0)
    ax.set_xscale("log")
    ax.set_xticks([0.5, 1, 2, 4, 8])
    ax.set_xticklabels(["0.5x", "1x = plain ReSTIR\nas shipped", "2x", "4x", "8x"])
    ax.minorticks_off()
    ax.set_yticks(ticks)
    ax.set_yticklabels(names, fontsize=10, color=INK)
    ax.set_xlabel("error in the medium after the denoiser, relative to plain ReSTIR as shipped (log scale; lower is better)",
                  fontsize=10, color=INK)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(axis="x", which="both", colors=MUTED, labelsize=9)
    ax.tick_params(axis="y", length=0)
    handles = [plt.Line2D([], [], marker="o", ls="", color=c, markersize=8, label=l)
               for c, l in ((BLUE, "ReSTIR + OptiX"), (ORANGE, "ReSTIR + 5 mutations + OptiX"))]
    ax.legend(handles=handles, loc="upper right", frameon=False, fontsize=10)
    fig.suptitle("A long history (M cap 200) makes plain ReSTIR up to 6x worse after the denoiser; 5 mutations recover\n"
                 "most of that, and on the lanterns and the concert end below the shipped setting. At the shipped M cap\n"
                 "they cut the error 3-26%. (2 independent frames per point; mutations alone, no decoupled history)",
                 fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    out = a.out or os.path.join(a.root, "figs", "settings_chart.png")
    fig.savefig(out, dpi=110, facecolor=fig.get_facecolor())
    print(out)


if __name__ == "__main__":
    main()
