"""The paper's new figures (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E6) from run_five.sh's runs
and five_scores.py's results:
- the teaser: the setup whose median cut over the five denoisers at M cap 200 is largest -- each denoiser before and
  after 5 mutations, and the reference, in the box where plain ReSTIR + OptiX errs most;
- the strip: STRIP's setups, the same layout one row each;
- the history chart: per denoiser, each setup's denoised relMSE with mutations over without, at the shipped cap and
  at M cap 200; and M cap 200 with mutations over plain ReSTIR at the shipped cap.

    python five_figures.py <root> [--results <root>/five_denoisers/results.json]
"""
import argparse
import json
import os
import sys
import textwrap

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art  # noqa: E402
import five_scores  # noqa: E402
import m_corr as mc  # noqa: E402
import paper_figure  # noqa: E402
import paper_tables  # noqa: E402
from variety_figures import EXPOSURE, PAPER_DISPLAY  # noqa: E402

DENOISERS = ("optix", "oidn", "relax", "reblur", "rr")
NAMES = {"optix": "OptiX", "oidn": "OIDN", "relax": "NRD RELAX", "reblur": "NRD REBLUR", "rr": "DLSS RR"}
STRIP = ["bunnycathedral_d0.3", "bunnylanterns", "explosiondusk_b2", "bunnyswarm_d3"]
# dataviz reference palette, light mode: categorical slots 1 and 2 (validated all-pairs), text and recessive ink.
BLUE, ORANGE, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#d9d8d4"


def cut(results, label, hist, den):
    c = results[label]["histories"][hist]
    return 1.0 - c["m5"][den]["mean"] / c["m0"][den]["mean"]


def complete(results, label, hist="c200"):
    c = results[label]["histories"].get(hist, {})
    return all(den in c.get(m, {}) for m in ("m0", "m5") for den in DENOISERS)


def teaser_setup(results):
    ok = [label for label in results if complete(results, label)]
    return max(ok, key=lambda label: float(np.median([cut(results, label, "c200", d) for d in DENOISERS])))


def _frame(root, results, label, hist, m, den):
    run = os.path.join(root, results[label]["histories"][hist]["m%d" % m][den]["run"])
    return five_scores.frames(run, five_scores.channels(run)[den])[0]  # chain 0's capture


def panel(root, results, label, hist="c200"):
    """Before/after per denoiser (chain 0), the reference, the zoom box and the display function."""
    ref = art.reference(root, label)
    mask = np.load(os.path.join(root, label, "noreuse", "c.medium.npy"))
    imgs = {d: (_frame(root, results, label, hist, 0, d), _frame(root, results, label, hist, 5, d)) for d in DENOISERS}
    size = max(64, min(ref.shape[:2]) // 5)
    (y, x), = paper_figure.pick_boxes(imgs["optix"][0], ref, size, n=1, mask=mask)
    if label in PAPER_DISPLAY:
        show = art.srgb_display
    else:
        k = np.percentile((ref @ mc.Y_RGB)[mask], EXPOSURE.get(label, 99.0)) + 1e-9
        show = lambda img: art.tonemap(img, k)  # noqa: E731
    return imgs, ref, show, (y, x, size)


def _header(axes):
    """Over the top row: each denoiser's name centred on its before/after pair, then 'plain' / '+ 5 mutations'."""
    def note(ax, text, x, dy, color=INK, **kw):
        ax.annotate(text, xy=(x, 1.0), xycoords="axes fraction", xytext=(0, dy), textcoords="offset points",
                    ha="center", va="bottom", fontsize=6, color=color, annotation_clip=False, **kw)
    for i, d in enumerate(DENOISERS):
        note(axes[2 * i], NAMES[d], 1.0, 18, fontweight="bold")  # the pair's centre: the right edge of its left panel
        note(axes[2 * i], "plain", 0.5, 10, color=MUTED)
        note(axes[2 * i + 1], "+ 5 mutations", 0.5, 10, color=MUTED)
    note(axes[-1], "reference", 0.5, 18, fontweight="bold")


def _row(axes, root, results, label, hist, titles):
    imgs, ref, show, (y, x, s) = panel(root, results, label, hist)
    c = results[label]["histories"][hist]
    cells = []
    for d in DENOISERS:
        cells.append((imgs[d][0], "%.4f" % c["m0"][d]["mean"]))
        change = ("%+.0f%%" % (-100 * cut(results, label, hist, d))).replace("-", "−")
        cells.append((imgs[d][1], "%.4f (%s)" % (c["m5"][d]["mean"], change)))
    cells.append((ref, ""))
    for ax, (img, title) in zip(axes, cells):
        ax.imshow(show(img[y:y + s, x:x + s]), interpolation="nearest")
        ax.set_xticks([])
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_edgecolor(GRID)
        ax.set_title(title, fontsize=6, color=INK, pad=2)
    if titles:
        _header(axes)
    axes[0].set_ylabel(textwrap.fill(paper_tables.SETUP_NAMES.get(label, label), 14), fontsize=6, color=INK)


def strip(root, results, labels, out, hist="c200"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(len(labels), 11, figsize=(7.1, 0.82 * len(labels) + 0.35), squeeze=False,
                             gridspec_kw={"wspace": 0.03, "hspace": 0.32})
    for i, label in enumerate(labels):
        _row(axes[i], root, results, label, hist, titles=(i == 0))
    fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def history_chart(results, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 2.4), gridspec_kw={"wspace": 0.28})
    labels = [l for l in results if complete(results, l) and complete(results, l, "ship")]
    for i, d in enumerate(DENOISERS):
        for hist, colour, dx in (("ship", BLUE, -0.12), ("c200", ORANGE, 0.12)):
            r = [results[l]["histories"][hist]["m5"][d]["mean"] / results[l]["histories"][hist]["m0"][d]["mean"]
                 for l in labels]
            a.scatter(np.full(len(r), i + dx), r, s=22, color=colour, edgecolors="white", linewidths=0.8, zorder=3,
                      label=("shipped cap" if hist == "ship" else "M cap 200") if i == 0 else None)
            a.plot([i + dx - 0.09, i + dx + 0.09], [np.median(r)] * 2, color=INK, lw=1.2, zorder=4)
        r = [results[l]["histories"]["c200"]["m5"][d]["mean"] / results[l]["histories"]["ship"]["m0"][d]["mean"]
             for l in labels]
        b.scatter(np.full(len(r), i), r, s=22, color=ORANGE, edgecolors="white", linewidths=0.8, zorder=3)
        b.plot([i - 0.09, i + 0.09], [np.median(r)] * 2, color=INK, lw=1.2, zorder=4)
    for ax, ylabel in ((a, "relMSE, 5 mutations / plain"), (b, "M cap 200 + 5 mutations /\nplain at the shipped cap")):
        ax.set_yscale("log")
        ax.axhline(1.0, color=MUTED, lw=0.8, zorder=1)
        ax.set_xticks(range(len(DENOISERS)))
        ax.set_xticklabels([NAMES[d].replace("NRD ", "") for d in DENOISERS], fontsize=7, color=INK)  # fits the width
        ax.set_ylabel(ylabel, fontsize=7, color=INK)
        ax.tick_params(axis="y", labelsize=7, colors=MUTED)
        ax.grid(axis="y", color=GRID, lw=0.5, zorder=0)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    a.legend(fontsize=7, frameon=False, loc="lower left")
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--results")
    a = ap.parse_args(argv)
    with open(a.results or os.path.join(a.root, "five_denoisers", "results.json")) as fh:
        results = json.load(fh)
    figs = os.path.join(a.root, "figs")
    t = teaser_setup(results)
    print("teaser:", t)
    strip(a.root, results, [t], os.path.join(figs, "teaser_five.png"))
    strip(a.root, results, STRIP, os.path.join(figs, "five_strip.png"))
    history_chart(results, os.path.join(figs, "history_chart.pdf"))


if __name__ == "__main__":
    main()
