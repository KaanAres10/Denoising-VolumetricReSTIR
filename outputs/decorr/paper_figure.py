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


def pick_boxes(a, ref, size, n=2, mask=None):
    """Top-left corners of n non-overlapping size x size windows with the largest blurred error of a, among windows
    at least half as bright as the lit area on average (dim wisps are noisy in the reference too) and, with a medium
    mask, mostly inside the medium (an emitter's edge in view is the denoiser's, not reuse's)."""
    inside = mask if mask is not None else np.ones(ref.shape[:2], bool)
    clip = np.percentile(ref[inside], 99.5)
    err = np.abs(np.minimum(a, clip) - np.minimum(ref, clip)).sum(axis=-1) * inside
    level = np.minimum(ref, clip).sum(axis=-1)
    e = cv2.blur(cv2.GaussianBlur(err.astype(np.float32), (0, 0), 6), (size, size))
    l = cv2.blur((level * inside).astype(np.float32), (size, size))
    lit = (level > 0.03 * np.percentile(level[inside], 99)) & inside
    frac = cv2.blur(inside.astype(np.float32), (size, size))
    bright = l >= 0.5 * (level[lit].mean() if lit.any() else level.mean())
    # Strictest first; relaxed (a dark backlit medium, a thin one) until some window qualifies.
    for need_bright, need_frac in ((True, 0.6), (False, 0.6), (False, 0.3), (False, 0.0)):
        score = e * ((frac >= need_frac) & (bright if need_bright else True))
        if score[size // 2:-(size // 2), size // 2:-(size // 2)].max() > 0:
            break
    h = size // 2
    fallback = e * (frac > 0)
    for s in (score, fallback):
        s[:h, :] = s[-h:, :] = 0
        s[:, :h] = s[:, -h:] = 0
    boxes = []
    for _ in range(n):
        s = score if score.max() > 0 else fallback  # the qualifying windows can all lie next to the first box
        y, x = np.unravel_index(np.argmax(s), s.shape)
        boxes.append((y - h, x - h))
        for s in (score, fallback):
            s[max(0, y - size):y + size, max(0, x - size):x + size] = 0
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
    ap.add_argument("--exposure-pct", type=float, default=99.0,
                    help="percentile of the medium's luminance mapped to white (higher: a bright beam keeps its texture)")
    a = ap.parse_args(argv)
    p = prepare(a.root, a.label, a.without, a.with_, a.exposure_pct)
    ref, imgs, inside, size, boxes, k, relmse = p.ref, p.imgs, p.inside, p.size, p.boxes, p.k, p.relmse
    names = a.names.split(",") + ["path-traced reference"]
    fig = plt.figure(figsize=(18, 13.2 + (5.6 if a.errors else 0)), facecolor="white")
    rows = 4 if a.errors else 3
    gs = fig.add_gridspec(rows, 6, height_ratios=[1.0, 0.62, 0.62] + ([1.0] if a.errors else []), hspace=0.12, wspace=0.04)
    draw(fig, gs, a, p, names)
    fig.suptitle(a.title, fontsize=15, y=0.995)
    out = a.out or os.path.join(a.root, "figs", "paper_%s_%s.png" % (a.label, a.with_))
    fig.savefig(out, dpi=90, bbox_inches="tight")
    plt.close(fig)
    print(out)
    return [relmse(img) for img in imgs]  # in the medium, this frame: without, with


def prepare(root, label, without, with_, exposure_pct=99.0):
    """The frames (without / with mutations) and the reference cropped to the medium, its mask, the zoom boxes, the
    exposure and the in-medium relMSE function -- shared by this figure and gallery_figure.py."""
    import types
    ref = art.reference(root, label)
    imgs = [art.kept(os.path.join(root, label, c))[0] for c in (without, with_)]
    # The medium (the no-reuse run's mask): the crop, the zoom boxes and the numbers stay inside it, so emitters in
    # view (whose edges the denoiser softens) neither draw the boxes nor dominate the error.
    mp = os.path.join(root, label, "noreuse", "c.medium.npy")
    mask = np.load(mp) if os.path.exists(mp) else None
    if mask is not None and mask.shape == ref.shape[:2] and mask.any():
        ys, xs = np.nonzero(mask)
        my, mx = int(0.04 * ref.shape[0]), int(0.04 * ref.shape[1])
        y0, y1 = max(0, ys.min() - my), min(ref.shape[0], ys.max() + my)
        x0, x1 = max(0, xs.min() - mx), min(ref.shape[1], xs.max() + mx)
        mask = mask[y0:y1, x0:x1]
    else:
        mask = None
        y0, y1, x0, x1 = lit_region(ref)
    ref = ref[y0:y1, x0:x1]
    imgs = [img[y0:y1, x0:x1] for img in imgs]
    size = max(64, min(ref.shape[:2]) // 4)
    boxes = pick_boxes(imgs[0], ref, size, mask=mask)
    inside = mask if mask is not None else np.ones(ref.shape[:2], bool)
    lref = ref @ mc.Y_RGB
    k = np.percentile(lref[inside], exposure_pct) + 1e-9

    # Clipped at the medium's brightest 0.5%: a light inside the medium (the lanterns) makes a few pixels huge, and
    # one frame's error there would decide the number.
    cl = np.percentile(lref[inside], 99.5)

    def relmse(img):
        d = (np.minimum(img @ mc.Y_RGB, cl) - np.minimum(lref, cl))[inside]
        return float(np.mean(d ** 2) / max(np.mean(np.minimum(lref, cl)[inside] ** 2), 1e-20))
    return types.SimpleNamespace(ref=ref, imgs=imgs, mask=mask, inside=inside, size=size, boxes=boxes, k=k,
                                 relmse=relmse, label=label, configs=(without, with_), crop=np.s_[y0:y1, x0:x1])


def draw(fig, gs, a, p, names):
    ref, imgs, inside, size, boxes, k, relmse = p.ref, p.imgs, p.inside, p.size, p.boxes, p.k, p.relmse
    if a.errors:
        # Signed error vs the reference, lightly blurred (sigma 2), luminance: the blotches a denoiser leaves.
        errs = [cv2.GaussianBlur(((img - ref) @ mc.Y_RGB).astype(np.float32), (0, 0), 2) * inside for img in imgs]
        lim = max(np.percentile(np.abs(e[inside]), 99) for e in errs)
        for j, e in enumerate(errs):
            ax = fig.add_subplot(gs[3, 2 * j:2 * j + 2])
            ax.imshow(e, cmap="RdBu_r", vmin=-lim, vmax=lim)
            ax.set_title("error vs reference, in the medium\n(red too bright, blue too dark)  RMS %.4f"
                         % float(np.sqrt(np.mean(e[inside] ** 2))), fontsize=11)
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
            corrs = []
            if rho is not None:
                corrs.append("blotch corr. %.3f" % rho)
            if col is not None and col > 1e-3:
                corrs.append("colour corr. %.3f" % col)
            info = "\nrelMSE in the medium %.4f" % relmse(img) + ("\n" + ", ".join(corrs) if corrs else "")
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


if __name__ == "__main__":
    main()
