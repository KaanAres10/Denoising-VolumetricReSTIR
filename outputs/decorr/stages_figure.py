"""The mutation speed-up's stages side by side, with plain ReSTIR next to them (user, 2026-10-07: "show all visual
comparisons between original, stage 1 and stage 2"; "compare without mutation as well"), per scene setup, from what
was captured:

  - raw ReSTIR output (no denoiser), 1080p, M cap 200, 192 warm-up frames, the same frame of each (one schedule):
    no mutations (run_cost.sh's mut0), and 5 mutations of every kind with the original shader
    (speed_ab/stage1/<label>/A1), Stage 1 (stage1/B1) and Stage 2's coherent moves (stage2/B1) -- with each one's
    Mutate Samples time, the whole pass's time and its error vs the reference;
  - denoised through OptiX (V-C2's runs): den_optix_mut0cap200 (no mutations), den_optix_mut5cap200, rendered with
    the original shader, whose input Stage 1 reproduces bit for bit, and den_optix_mut5cohcap200 (Stage 2).

The zoom box goes where plain ReSTIR's denoised error is largest (paper_figure.py): where reuse's artifacts are.

    python stages_figure.py <root> [labels...]   (root: outputs/decorr; writes figs/stages_<label>.png)
    python stages_figure.py <root> --gallery      (every setup on one page: figs/stages_gallery.png)
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
DEN = ("den_optix_mut0cap200", "den_optix_mut5cap200", "den_optix_mut5cohcap200")  # none, original = Stage 1, Stage 2
RAW = (("cost", "mut0"), ("speed_ab/stage1", "A1"), ("speed_ab/stage1", "B1"), ("speed_ab/stage2", "B1"))
NAMES = ("No mutations", "Original", "Stage 1 (shared p\u0302, exact)", "Stage 2 (coherent moves)")


def raw_frames(root, label):
    """Every captured frame of each RAW run, in frame order (the same frame numbers in each: one schedule), the first
    frame's number, and the original vs Stage 1 comparison of all of them, for the bit-identity line."""
    runs, first = [], None
    for where, run in RAW:
        f = ab._frames(os.path.join(root, where, label, run), ".exr")
        first = min(f)
        runs.append([mc.read_exr(f[k])[..., :3][..., ::-1].astype(np.float64) for k in sorted(f)])
    same = ab.compare(os.path.join(root, "speed_ab", "stage1", label, "A1"),
                      os.path.join(root, "speed_ab", "stage1", label, "B1"))
    return runs, same, first


def times(root, label):
    """(Mutate Samples ms, whole VolumetricReSTIR ms) per RAW column: plain's from its timing run (run_cost.sh),
    the others the mean of their A/B runs."""
    t1 = ab.times(os.path.join(root, "speed_ab", "stage1", label))
    t2 = ab.times(os.path.join(root, "speed_ab", "stage2", label))
    plain = ab._lane(os.path.join(root, "cost", label, "mut0"))
    return [(0.0, plain)] + [(t["mutate"], t["total"]) for t in (t1["A"], t1["B"], t2["B"])]


def denoised(root, label):
    """paper_figure's preparation with plain ReSTIR first (it places the zoom boxes), and the three denoised frames
    cropped like the reference."""
    p = paper_figure.prepare(root, label, DEN[0], DEN[1], vf.EXPOSURE.get(label, 99.0), label in vf.PAPER_DISPLAY)
    stage2 = art.kept(os.path.join(root, label, DEN[2]))[0][p.crop]
    return p, list(p.imgs) + [stage2]


def error_map(img, ref, inside):
    return cv2.GaussianBlur(((img - ref) @ mc.Y_RGB).astype(np.float32), (0, 0), 2) * inside


def make(root, label, out):
    p, den = denoised(root, label)
    runs, same, frame = raw_frames(root, label)
    runs = [[img[p.crop] for img in r] for r in runs]
    raw = [r[0] for r in runs]
    raw_rel = [float(np.mean([p.relmse(img) for img in r])) for r in runs]
    ms = times(root, label)
    ref, inside, size = p.ref, p.inside, p.size
    (y, x) = p.boxes[0]
    box = np.s_[y:y + size, x:x + size]

    fig = plt.figure(figsize=(25, 30), facecolor="white")
    gs = fig.add_gridspec(6, 5, height_ratios=[1.0, 0.9, 1.0, 1.0, 0.9, 1.0], hspace=0.4, wspace=0.07,
                          top=0.905, bottom=0.01)
    fig.suptitle(vf.TITLES.get(label, label) + "\nplain ReSTIR, and 5 mutations before and after the speed-up",
                 fontsize=19, y=0.995)
    fig.text(0.5, 0.962, "Rows 1-3: raw ReSTIR output (no denoiser), frame %d, 1080p, M cap 200 (no mutations: its timing "
             "run; with mutations: the speed A/B).   Rows 4-6: the same through OptiX (V-C2's quality runs)." % frame,
             ha="center", fontsize=13)

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
            ax.set_title("error vs reference (red too bright, blue too dark)\nRMS %.4f"
                         % float(np.sqrt(np.mean(e[inside] ** 2))), fontsize=11)
            ax.axis("off")

    # Raw: none | original | Stage 1 | Stage 2 | reference.
    for j, (img, name) in enumerate(zip(raw, NAMES)):
        if j == 0:
            timing = "no mutation pass\nwhole pass %.1f ms" % ms[0][1]
        else:
            timing = "Mutate Samples %.1f ms%s\nwhole pass %.1f ms" % (
                ms[j][0], "" if j == 1 else " (%+.0f%%)" % (100 * (ms[j][0] / ms[1][0] - 1)), ms[j][1])
        panel(gs[0, j], img, "%s, raw\n%s\nrelMSE in the medium %.4f\n(4-frame mean)" % (name, timing, raw_rel[j]))
        panel(gs[1, j], img, "", zoom=True)
    panel(gs[0, 4], ref, "path-traced reference")
    panel(gs[1, 4], ref, "", zoom=True)
    errors(2, raw, (0, 1, 2, 3))
    ax = fig.add_subplot(gs[2, 4])
    ax.text(0.5, 0.5, "Same colour scale in all maps.\n\nStage 1 vs original: %d/%d frames\nbit-identical (%d pixels differ)."
            "\n\nStage 2 draws its move kinds from\na stream all pixels share: a different\nrandom realization of the same"
            "\nestimator, so its noise differs pixel\nby pixel, not its error level."
            % (same["identical"], same["frames"], same["pixels_differ"]), ha="center", va="center", fontsize=12,
            transform=ax.transAxes)
    ax.axis("off")

    # Denoised: none | original (= Stage 1's input) | note | Stage 2 | reference.
    colour = paper_figure.BOX_COLOURS[1]
    for j, (img, name, col) in enumerate(zip(den, ("No mutations", "Original = Stage 1", "Stage 2 (coherent moves)"),
                                             (0, 1, 3))):
        panel(gs[3, col], img, "%s, OptiX\nrelMSE in the medium %.4f" % (name, p.relmse(img)), colour=colour)
        panel(gs[4, col], img, "", zoom=True, colour=colour)
    ax = fig.add_subplot(gs[3, 2])
    ax.text(0.5, 0.5, "Stage 1's denoised frame is the original's:\nits input to OptiX is bit-identical\n"
            "(not rendered a second time).", ha="center", va="center", fontsize=12, transform=ax.transAxes)
    ax.axis("off")
    panel(gs[3, 4], ref, "path-traced reference", colour=colour)
    panel(gs[4, 4], ref, "", zoom=True, colour=colour)
    errors(5, den, (0, 1, 3))
    fig.savefig(out, dpi=72, bbox_inches="tight")
    plt.close(fig)
    return out


def gallery(root, out, labels=LABELS):
    """Every setup on one page, one row each: the zoom box of the raw frames (none, original, Stage 1, Stage 2), of
    the denoised ones (none, original = Stage 1, Stage 2) and of the reference, with times and in-medium relMSE."""
    cols = ("raw: no mutations", "raw: original", "raw: Stage 1", "raw: Stage 2", "OptiX: no mutations",
            "OptiX: original = Stage 1", "OptiX: Stage 2", "reference")
    fig, axes = plt.subplots(len(labels), len(cols), figsize=(3.1 * len(cols), 3.45 * len(labels)), facecolor="white")
    fig.subplots_adjust(top=0.948, bottom=0.005, left=0.045, right=0.997, hspace=0.32, wspace=0.04)
    fig.suptitle("Plain ReSTIR, and 5 mutations before and after the speed-up: zoomed crops at M cap 200\n"
                 "(raw = ReSTIR output, one frame; OptiX = V-C2's denoised runs; whole-pass ms for raw no mutations, "
                 "Mutate Samples ms for the others; relMSE in the medium)", fontsize=14)
    for i, label in enumerate(labels):
        p, den = denoised(root, label)
        runs, _, _ = raw_frames(root, label)
        raw = [r[0][p.crop] for r in runs]
        ms = times(root, label)
        (y, x), size = p.boxes[0], p.size
        imgs = raw + den + [p.ref]
        notes = ["pass %.1f ms, %.4f" % (ms[0][1], p.relmse(raw[0]))] + \
                ["%.1f ms, %.4f" % (ms[j][0], p.relmse(raw[j])) for j in range(1, 4)] + \
                ["%.4f" % p.relmse(img) for img in den] + [""]
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
