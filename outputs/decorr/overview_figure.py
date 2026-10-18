"""One overview of several plain-ReSTIR vs mutation pairs on one label (rows), each as paper_figure.py prepares it:
ReSTIR, ReSTIR + mutations and the path-traced reference, full frame and the same zoom box in every row (the
first pair's largest-error box), each labelled with its relMSE in the medium.

    python overview_figure.py <root> <label> <out.png> <title> <without>,<with>,<row title> [...]
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_figure as pf  # noqa: E402


def main(argv):
    root, label, out, title = argv[:4]
    rows = [r.split(",", 2) for r in argv[4:]]
    ps = [pf.prepare(root, label, a, b) for a, b, _ in rows]
    by, bx = ps[0].boxes[0][:2]
    s = ps[0].size
    fig, axes = plt.subplots(len(rows), 6, figsize=(22, 3.3 * len(rows)),
                             gridspec_kw={"width_ratios": [2.2, 2.2, 2.2, 1, 1, 1]})
    for r, ((a, b, name), p) in enumerate(zip(rows, ps)):
        e = [p.relmse(img) for img in p.imgs]
        panels = [(p.imgs[0], "ReSTIR\nrelMSE %.4f" % e[0]),
                  (p.imgs[1], "ReSTIR + 5 mutations\nrelMSE %.4f  (%+.0f%%)" % (e[1], 100 * (e[1] / e[0] - 1))),
                  (p.ref, "path-traced reference")]
        for c, (img, t) in enumerate(panels):
            d = np.clip(p.show(img), 0, 1)
            axes[r, c].imshow(d)
            axes[r, c].add_patch(plt.Rectangle((bx, by), s, s, fill=False, ec="orange", lw=1.5))
            axes[r, c].set_title(t, fontsize=11)
            axes[r, 3 + c].imshow(d[by:by + s, bx:bx + s], interpolation="nearest")
            axes[r, 3 + c].set_title(["zoom", "zoom", "zoom"][c], fontsize=10)
        axes[r, 0].set_ylabel(name, fontsize=12, rotation=0, ha="right", va="center", labelpad=12)
    for ax in axes.ravel():
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle(title, fontsize=15)
    fig.tight_layout(rect=(0.06, 0, 1, 0.97))
    fig.savefig(out, dpi=90)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1:])
