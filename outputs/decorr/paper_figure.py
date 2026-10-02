"""A comparison in the style of Sawhney et al. 2024's figures: plain ReSTIR vs the same ReSTIR with mutations,
both through a denoiser (or raw), next to the path-traced reference. Full frames on top with two zoom boxes,
the boxes enlarged below. The boxes go where plain ReSTIR's error is largest (blurred, relative to the
reference's level, ignoring the darkest areas and the brightest 0.5% of pixels), which is where its artifacts are.

    python paper_figure.py <root> <label> <config without> <config with> [--title T] [--out F]
"""
import argparse
import json
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art
import m_corr as mc

BOX_COLOURS = ("#eda100", "#1baf7a")  # reference palette slots 4 and 3


def lit_region(ref, margin=0.06):
    """The bounding box (y0, y1, x0, x1) of the lit part of the frame, with a margin: the medium and what it lights."""
    lum = ref @ mc.Y_RGB
    ys, xs = np.nonzero(cv2.blur(lum.astype(np.float32), (9, 9)) > 0.03 * np.percentile(lum, 99))
    if len(ys) == 0:
        return 0, ref.shape[0], 0, ref.shape[1]
    my, mx = int(margin * ref.shape[0]), int(margin * ref.shape[1])
    return max(0, ys.min() - my), min(ref.shape[0], ys.max() + my), max(0, xs.min() - mx), min(ref.shape[1], xs.max() + mx)


def pick_boxes(a, ref, size, n=2):
    """Top-left corners of n non-overlapping size x size windows with the largest blurred error of a, among windows
    at least half as bright as the lit area on average (dim wisps are noisy in the reference too)."""
    clip = np.percentile(ref, 99.5)
    err = np.abs(np.minimum(a, clip) - np.minimum(ref, clip)).sum(axis=-1)
    level = np.minimum(ref, clip).sum(axis=-1)
    e = cv2.blur(cv2.GaussianBlur(err.astype(np.float32), (0, 0), 6), (size, size))
    l = cv2.blur(level.astype(np.float32), (size, size))
    lit = level > 0.03 * np.percentile(level, 99)
    score = e.copy()
    score[l < 0.5 * (level[lit].mean() if lit.any() else level.mean())] = 0
    h = size // 2
    score[:h, :] = score[-h:, :] = 0
    score[:, :h] = score[:, -h:] = 0
    boxes = []
    for _ in range(n):
        y, x = np.unravel_index(np.argmax(score), score.shape)
        boxes.append((y - h, x - h))
        score[max(0, y - size):y + size, max(0, x - size):x + size] = 0
    return boxes


def corr(root, label, cfg):
    p = os.path.join(root, label, cfg, "c.corr.json")
    return json.load(open(p)) if os.path.exists(p) else {}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("label")
    ap.add_argument("without")
    ap.add_argument("with_")
    ap.add_argument("--title", default="")
    ap.add_argument("--names", default="ReSTIR,ReSTIR + 5 mutations")
    ap.add_argument("--out")
    ap.add_argument("--errors", action="store_true", help="a row of signed error maps vs the reference")
    a = ap.parse_args(argv)
    ref = art.reference(a.root, a.label)
    imgs = [art.kept(os.path.join(a.root, a.label, c))[0] for c in (a.without, a.with_)]
    y0, y1, x0, x1 = lit_region(ref)
    ref = ref[y0:y1, x0:x1]
    imgs = [img[y0:y1, x0:x1] for img in imgs]
    names = a.names.split(",") + ["path-traced reference"]
    size = max(64, min(ref.shape[:2]) // 4)
    boxes = pick_boxes(imgs[0], ref, size)
    k = np.percentile(ref @ mc.Y_RGB, 99) + 1e-9
    fig = plt.figure(figsize=(18, 13.2 + (5.6 if a.errors else 0)), facecolor="white")
    rows = 4 if a.errors else 3
    gs = fig.add_gridspec(rows, 6, height_ratios=[1.0, 0.62, 0.62] + ([1.0] if a.errors else []), hspace=0.12, wspace=0.04)
    if a.errors:
        # Signed error vs the reference, lightly blurred (sigma 2), luminance: the blotches a denoiser leaves.
        errs = [cv2.GaussianBlur(((img - ref) @ mc.Y_RGB).astype(np.float32), (0, 0), 2) for img in imgs]
        lim = max(np.percentile(np.abs(e), 99) for e in errs)
        for j, e in enumerate(errs):
            ax = fig.add_subplot(gs[3, 2 * j:2 * j + 2])
            ax.imshow(e, cmap="RdBu_r", vmin=-lim, vmax=lim)
            ax.set_title("error vs reference (red too bright, blue too dark)\nRMS %.4f" % float(np.sqrt(np.mean(e ** 2))),
                         fontsize=11)
            ax.axis("off")
        ax = fig.add_subplot(gs[3, 4:6])
        ax.text(0.5, 0.5, "Same colour scale in both maps.\nThe red and blue patches in the first map are\n"
                "reuse's blotches, which the denoiser keeps\n(it cannot tell correlated error from detail).\n"
                "The second map is what is left with mutations.",
                ha="center", va="center", fontsize=12, transform=ax.transAxes)
        ax.axis("off")
    for j, (img, name) in enumerate(zip(imgs + [ref], names)):
        ax = fig.add_subplot(gs[0, 2 * j:2 * j + 2])
        ax.imshow(art.tonemap(img, k))
        info = ""
        if j < 2:
            c = corr(a.root, a.label, (a.without, a.with_)[j])
            rho = (c.get("medium") or c.get("robust") or {}).get("rho", {}).get("8")
            col = c.get("color_rb", {}).get("rho", {}).get("8")
            rel = c.get("reference", {}).get("relmse")
            parts = []
            if rel is not None:
                parts.append("relMSE %.4f" % rel)
            if rho is not None:
                parts.append("blotch corr. %.4f" % rho)
            if col is not None and col > 1e-3:
                parts.append("colour corr. %.4f" % col)
            info = "\n" + ", ".join(parts)
        ax.set_title(name + info, fontsize=12)
        for (y, x), colour in zip(boxes, BOX_COLOURS):
            ax.add_patch(Rectangle((x, y), size, size, fill=False, ec=colour, lw=2.2))
        ax.axis("off")
        for b, ((y, x), colour) in enumerate(zip(boxes, BOX_COLOURS)):
            ax2 = fig.add_subplot(gs[1 + b, 2 * j:2 * j + 2])
            ax2.imshow(art.tonemap(img[y:y + size, x:x + size], k), interpolation="nearest")
            for s in ax2.spines.values():
                s.set_edgecolor(colour)
                s.set_linewidth(3)
            ax2.set_xticks([])
            ax2.set_yticks([])
    fig.suptitle(a.title, fontsize=15, y=0.995)
    out = a.out or os.path.join(a.root, "figs", "paper_%s_%s.png" % (a.label, a.with_))
    fig.savefig(out, dpi=90, bbox_inches="tight")
    print(out)


if __name__ == "__main__":
    main()
