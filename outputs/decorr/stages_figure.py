"""The mutation speed-up's stages side by side (user, 2026-10-07: "show all visual comparisons between original,
stage 1 and stage 2"), per scene setup, from what was captured:

  - raw ReSTIR output (no denoiser) of the speed A/B runs: 1080p, M cap 200, 5 mutations of every kind, 192 warm-up
    frames, the same frame of each -- the original shader (speed_ab/stage1/<label>/A1), Stage 1 (stage1/B1) and
    Stage 2's coherent moves (stage2/B1) -- with each one's Mutate Samples time and its error vs the reference;
  - denoised through OptiX (V-C2's runs): den_optix_mut5cap200, rendered with the original shader, whose input
    Stage 1 reproduces bit for bit, and den_optix_mut5cohcap200 (Stage 2), with error maps.

    python stages_figure.py <root> [labels...]        (root: outputs/decorr; writes figs/stages_<label>.png)
"""
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art
import m_corr as mc
import paper_figure
import speed_ab_check as ab
import variety_figures as vf

LABELS = ["explosiondusk", "explosiondusk_b2", "bunnycathedral_d0.3", "bunnycathedral_d0.3_b2", "bunnyback_g0.8",
          "bunnyback_g0.8_b2", "bunnysoftbox", "bunnysoftbox_b2", "wdassunset_g0.85", "wdassunset_g0.85_b2"]
DEN = ("den_optix_mut5cap200", "den_optix_mut5cohcap200")
RAW = (("stage1", "A1"), ("stage1", "B1"), ("stage2", "B1"))  # original, Stage 1, Stage 2
NAMES = ("Original", "Stage 1 (shared p\u0302, exact)", "Stage 2 (coherent moves)")


def raw_frames(root, label):
    """Every captured frame of each RAW run, in frame order (the same frame numbers in each: one schedule), the first
    frame's number, and the original vs Stage 1 comparison of all of them, for the bit-identity line."""
    runs, first = [], None
    for stage, run in RAW:
        f = ab._frames(os.path.join(root, "speed_ab", stage, label, run), ".exr")
        first = min(f)
        runs.append([mc.read_exr(f[k])[..., :3][..., ::-1].astype(np.float64) for k in sorted(f)])
    same = ab.compare(os.path.join(root, "speed_ab", "stage1", label, "A1"),
                      os.path.join(root, "speed_ab", "stage1", label, "B1"))
    return runs, same, first


def mutate_ms(root, label):
    t1 = ab.times(os.path.join(root, "speed_ab", "stage1", label))
    t2 = ab.times(os.path.join(root, "speed_ab", "stage2", label))
    return t1["A"]["mutate"], t1["B"]["mutate"], t2["B"]["mutate"]


def error_map(img, ref, inside):
    return cv2.GaussianBlur(((img - ref) @ mc.Y_RGB).astype(np.float32), (0, 0), 2) * inside


def make(root, label, out):
    p = paper_figure.prepare(root, label, DEN[0], DEN[1], vf.EXPOSURE.get(label, 99.0), label in vf.PAPER_DISPLAY)
    runs, same, frame = raw_frames(root, label)
    runs = [[img[p.crop] for img in r] for r in runs]
    raw = [r[0] for r in runs]
    raw_rel = [float(np.mean([p.relmse(img) for img in r])) for r in runs]
    ms = mutate_ms(root, label)
    ref, inside, size = p.ref, p.inside, p.size
    (y, x) = p.boxes[0]
    box = np.s_[y:y + size, x:x + size]

    fig = plt.figure(figsize=(20, 30), facecolor="white")
    gs = fig.add_gridspec(6, 4, height_ratios=[1.0, 0.9, 1.0, 1.0, 0.9, 1.0], hspace=0.36, wspace=0.05,
                          top=0.915, bottom=0.01)
    fig.suptitle(vf.TITLES.get(label, label) + "\nthe mutation pass before and after the speed-up", fontsize=18, y=0.995)
    fig.text(0.5, 0.962, "Rows 1-3: raw ReSTIR output (no denoiser), frame %d of the speed A/B, 1080p, M cap 200, 5 mutations "
             "of every kind.   Rows 4-6: the same through OptiX (V-C2's quality runs)." % frame, ha="center", fontsize=13)

    def panel(cell, img, title, boxed=True, zoom=False, colour=paper_figure.BOX_COLOURS[0]):
        ax = fig.add_subplot(cell)
        ax.imshow(p.show(img[box] if zoom else img), interpolation="nearest" if zoom else None)
        ax.set_title(title, fontsize=12)
        if zoom:
            for s in ax.spines.values():
                s.set_edgecolor(colour)
                s.set_linewidth(3)
            ax.set_xticks([])
            ax.set_yticks([])
        else:
            if boxed:
                ax.add_patch(Rectangle((x, y), size, size, fill=False, ec=colour, lw=2.2))
            ax.axis("off")

    def errors(row, imgs, cols):
        errs = [error_map(img, ref, inside) for img in imgs]
        lim = max(np.percentile(np.abs(e[inside]), 99) for e in errs)
        for e, c in zip(errs, cols):
            ax = fig.add_subplot(gs[row, c])
            ax.imshow(e, cmap="RdBu_r", vmin=-lim, vmax=lim)
            ax.set_title("error vs reference (red too bright, blue too dark)\nRMS %.4f" % float(np.sqrt(np.mean(e[inside] ** 2))),
                         fontsize=11)
            ax.axis("off")

    # Raw: original | Stage 1 | Stage 2 | reference.
    for j, (img, name) in enumerate(zip(raw, NAMES)):
        speed = "" if j == 0 else " (%+.0f%%)" % (100 * (ms[j] / ms[0] - 1))
        panel(gs[0, j], img, "%s, raw\nMutate Samples %.1f ms%s\nrelMSE in the medium %.4f (4-frame mean)"
              % (name, ms[j], speed, raw_rel[j]))
        panel(gs[1, j], img, "", zoom=True)
    panel(gs[0, 3], ref, "path-traced reference")
    panel(gs[1, 3], ref, "", zoom=True)
    errors(2, raw, (0, 1, 2))
    ax = fig.add_subplot(gs[2, 3])
    ident = ("Stage 1 vs original: %d/%d frames bit-identical\n(%d pixels differ)" % (same["identical"], same["frames"],
             same["pixels_differ"]))
    ax.text(0.5, 0.5, ident + "\n\nStage 2 draws its move kinds from a stream\nall pixels share: a different random "
            "realization\nof the same estimator, so its noise differs\npixel by pixel, not its error level.",
            ha="center", va="center", fontsize=12, transform=ax.transAxes)
    ax.axis("off")

    # Denoised: original (= Stage 1's input) | note | Stage 2 | reference.
    den = p.imgs
    colour = paper_figure.BOX_COLOURS[1]
    panel(gs[3, 0], den[0], "Original = Stage 1, OptiX\nrelMSE in the medium %.4f" % p.relmse(den[0]), colour=colour)
    panel(gs[4, 0], den[0], "", zoom=True, colour=colour)
    ax = fig.add_subplot(gs[3, 1])
    ax.text(0.5, 0.5, "Stage 1's denoised frame is the original's:\nits input to OptiX is bit-identical\n"
            "(not rendered a second time).", ha="center", va="center", fontsize=12, transform=ax.transAxes)
    ax.axis("off")
    panel(gs[3, 2], den[1], "Stage 2 (coherent moves), OptiX\nrelMSE in the medium %.4f" % p.relmse(den[1]), colour=colour)
    panel(gs[4, 2], den[1], "", zoom=True, colour=colour)
    panel(gs[3, 3], ref, "path-traced reference", colour=colour)
    panel(gs[4, 3], ref, "", zoom=True, colour=colour)
    errors(5, den, (0, 2))
    fig.savefig(out, dpi=72, bbox_inches="tight")
    plt.close(fig)
    return out


def gallery(root, out, labels=LABELS):
    """Every setup on one page, one row each: the zoom box of the raw frames (original, Stage 1, Stage 2), of the
    denoised ones (original = Stage 1, Stage 2) and of the reference, with the pass time and in-medium relMSE."""
    cols = ("raw: original", "raw: Stage 1", "raw: Stage 2", "OptiX: original = Stage 1", "OptiX: Stage 2", "reference")
    fig, axes = plt.subplots(len(labels), len(cols), figsize=(3.1 * len(cols), 3.45 * len(labels)), facecolor="white")
    fig.subplots_adjust(top=0.948, bottom=0.005, left=0.06, right=0.995, hspace=0.32, wspace=0.04)
    fig.suptitle("The mutation speed-up, stage by stage: zoomed crops at M cap 200, 5 mutations of every kind\n"
                 "(raw = ReSTIR output, one frame of the speed A/B; OptiX = V-C2's denoised runs; Mutate Samples ms, "
                 "relMSE in the medium)", fontsize=14)
    for i, label in enumerate(labels):
        p = paper_figure.prepare(root, label, DEN[0], DEN[1], vf.EXPOSURE.get(label, 99.0), label in vf.PAPER_DISPLAY)
        runs, _, _ = raw_frames(root, label)
        raw = [r[0][p.crop] for r in runs]
        ms = mutate_ms(root, label)
        (y, x), size = p.boxes[0], p.size
        imgs = raw + list(p.imgs) + [p.ref]
        notes = ["%.1f ms, %.4f" % (ms[j], p.relmse(raw[j])) for j in range(3)] + \
                ["%.4f" % p.relmse(img) for img in p.imgs] + [""]
        for j, (img, note) in enumerate(zip(imgs, notes)):
            ax = axes[i, j]
            ax.imshow(p.show(img[y:y + size, x:x + size]), interpolation="nearest")
            ax.set_title(("%s\n" % cols[j] if i == 0 else "") + note, fontsize=10)
            ax.set_xticks([])
            ax.set_yticks([])
        axes[i, 0].set_ylabel(label.replace("_b2", "\n2 bounces").replace("_", " "), fontsize=11)
    fig.savefig(out, dpi=72)
    plt.close(fig)
    return out


def main(argv):
    root = argv[1]
    if argv[2:] == ["--gallery"]:
        print(gallery(root, os.path.join(root, "figs", "stages_gallery.png")))
        return
    for label in argv[2:] or LABELS:
        print(make(root, label, os.path.join(root, "figs", "stages_%s.png" % label)))


if __name__ == "__main__":
    main(sys.argv)
