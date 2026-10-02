"""What averaging cannot remove: the average of a video's consecutive denoised frames (run_apparent.sh), per config,
next to the path-traced reference, with the averages' error maps. Independent error averages away over frames;
reuse's blotches persist (a long history reuses the same samples), so plain ReSTIR's average keeps them and the
mutated one converges.

    python persistence_figure.py <root> <label> [--configs restir,mut5,mut16] [--title T] [--out F]
"""
import argparse
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art
import m_corr as mc
from make_video import NAMES, burst_frames
from paper_figure import lit_region


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("label")
    ap.add_argument("--configs", default="restir,mut5,mut16")
    ap.add_argument("--title", default="")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    cfgs = [c for c in a.configs.split(",") if os.path.isdir(os.path.join(a.root, "video", a.label, c))]
    clips = [burst_frames(os.path.join(a.root, "video", a.label, c)) for c in cfgs]
    h, w = clips[0][0].shape[:2]
    ref = cv2.resize(art.reference(a.root, a.label).astype(np.float32), (w, h), interpolation=cv2.INTER_AREA).astype(np.float64)
    y0, y1, x0, x1 = lit_region(ref)
    lr = ref @ mc.Y_RGB
    lit = lr > 0.03 * np.percentile(lr, 99)

    def relmse(x):
        d = (x @ mc.Y_RGB - lr)[lit]
        return float(np.mean(d ** 2) / np.mean(lr[lit] ** 2))

    avgs = [np.mean(c, axis=0) for c in clips]
    per_frame = [np.mean([relmse(f) for f in c]) for c in clips]
    k = np.percentile(lr, 99) + 1e-9
    errs = [cv2.GaussianBlur(((m - ref) @ mc.Y_RGB).astype(np.float32), (0, 0), 2) for m in avgs]
    lim = np.percentile(np.abs(errs[0][lit]), 99.5)
    n = len(cfgs) + 1
    fig, ax = plt.subplots(2, n, figsize=(6.2 * n, 8.6), squeeze=False)
    for j, (c, m, e, pf) in enumerate(zip(cfgs, avgs, errs, per_frame)):
        ax[0][j].imshow(art.tonemap(m[y0:y1, x0:x1], k))
        ax[0][j].set_title("%s: average of %d frames\nrelMSE per frame %.4f -> of the average %.4f"
                           % (NAMES.get(c, c), len(clips[j]), pf, relmse(m)), fontsize=12)
        ax[1][j].imshow(e[y0:y1, x0:x1], cmap="RdBu_r", vmin=-lim, vmax=lim)
        ax[1][j].set_title("error of the average vs reference (red too bright, blue too dark)", fontsize=10)
    ax[0][n - 1].imshow(art.tonemap(ref[y0:y1, x0:x1], k))
    ax[0][n - 1].set_title("path-traced reference", fontsize=12)
    ax[1][n - 1].text(0.5, 0.5, "Same colour scale in every map.\nIndependent noise averages away over frames;\n"
                      "reuse's blotches persist, so plain ReSTIR's\naverage keeps them.",
                      ha="center", va="center", fontsize=12, transform=ax[1][n - 1].transAxes)
    for x in ax.ravel():
        x.axis("off")
    fig.suptitle(a.title, fontsize=14)
    out = a.out or os.path.join(a.root, "figs", "persistence_%s.png" % a.label)
    fig.savefig(out, dpi=90, bbox_inches="tight")
    print(out)


if __name__ == "__main__":
    main()
