"""run_counts.sh's figures (spec V-C7): figs/mutation_counts_curve.png, rho(8) in the medium and in colour against the
number of mutations per frame at M cap 200, one line per scene; figs/mutation_counts_gallery.png, per scene the same
frame (the first chain's first capture, raw, before any denoiser) without reuse and with 0, 1, 3, 10 and 20 mutations,
cropped where the 0-mutation frame is blotchiest and tone-mapped on one scale per scene.

    python counts_figures.py <outputs/decorr>
"""
import json
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import count_curve  # noqa: E402

LABELS = (("bunnyswarm_d3", "192 coloured lights, dense cloud"), ("bunnybeam", "a 1.4-degree beam"),
          ("bunnypinback_g0.97", "hidden backlight, g = 0.97"), ("bunnypinback_g0.97_b2", "hidden backlight, 2 bounces"),
          ("bunnyclosebox_b2", "large close panels, 2 bounces"))
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4")  # categorical slots 1-5, in order
SURFACE, INK, INK2, RULE, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#d6d4cc", "#ebeae5"
GALLERY = (("noreuse", "no reuse"), ("c200_m0", "plain ReSTIR"), ("c200_m1", "1 mutation"), ("c200_m3", "3 mutations"),
           ("c200_m10", "10 mutations"), ("c200_m20", "20 mutations"))
LUM = np.array([0.0722, 0.7152, 0.2126])  # BGR


def best_window(energy, w, h):
    """(y, x) of the h x w window with the largest summed energy (an integral image)."""
    ii = np.pad(energy, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    s = ii[h:, w:] - ii[:-h, w:] - ii[h:, :-w] + ii[:-h, :-w]
    y, x = np.unravel_index(np.argmax(s), s.shape)
    return int(y), int(x)


def tone(img, scale):
    return np.clip(img / scale, 0, 1) ** (1 / 2.2)


def frame(run_dir):
    p = os.path.join(run_dir, "c.schedule.json")
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        f = json.load(fh)["chains"][0]["frames"][0]
    exr = os.path.join(run_dir, "c.VolumetricReSTIR.accumulated_color.%d.exr" % f)
    if not os.path.exists(exr):
        return None
    return np.nan_to_num(cv2.imread(exr, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float64), posinf=0.0)


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(RULE)
    ax.tick_params(colors=INK2)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def curve_figure(root, out):
    counts = [0, 1, 2, 3, 5, 10, 20]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.6), facecolor=SURFACE)
    for ax, key, title in zip(axes, ("medium", "colour"), ("Neighbour correlation in the medium", "Colour correlation")):
        style(ax)
        for (label, name), col in zip(LABELS, SERIES):
            s = count_curve.load_counts(root, label, "c200")
            xs = [counts.index(n) for n in sorted(s) if n in counts]
            ys = [s[n][key] for n in sorted(s) if n in counts]
            if not xs:
                continue
            ax.plot(xs, ys, color=col, linewidth=2, marker="o", markersize=8, markeredgecolor=SURFACE, markeredgewidth=2,
                    label=name)
        ax.set_yscale("log")
        ax.set_xticks(range(len(counts)), [str(n) for n in counts])
        ax.set_xlabel("mutations per pixel per frame (M cap 200)", color=INK2)
        ax.set_title(title + ", ρ̄(8)", loc="left", color=INK, fontsize=13)
    axes[1].legend(frameon=False, labelcolor=INK2, fontsize=10, loc="upper right")
    fig.tight_layout()
    fig.savefig(out, dpi=130, facecolor=SURFACE)
    plt.close(fig)


def gallery_figure(root, out):
    rows = [(l, n) for l, n in LABELS if os.path.isdir(os.path.join(root, l, "c200_m0"))]
    if not rows:
        return
    fig, axes = plt.subplots(len(rows), len(GALLERY), figsize=(3.3 * len(GALLERY), 2.35 * len(rows) + 0.4),
                             facecolor=SURFACE, squeeze=False)
    for r, (label, name) in enumerate(rows):
        imgs = {cfg: frame(os.path.join(root, label, cfg)) for cfg, _ in GALLERY}
        base, ref = imgs.get("c200_m0"), imgs.get("noreuse")
        lum0 = base @ LUM
        # where the 0-mutation frame has the most low-frequency variation (blotches), within the lit medium
        blur = cv2.GaussianBlur(lum0, (0, 0), 4)
        energy = np.abs(blur - cv2.GaussianBlur(lum0, (0, 0), 16)) * (cv2.GaussianBlur(lum0, (0, 0), 8) > 0)
        mpath = os.path.join(root, label, "noreuse", "c.medium.npy")  # stay in the medium, off emitters seen directly
        med = np.load(mpath) if os.path.exists(mpath) else np.ones(lum0.shape, bool)
        inner = cv2.erode(med.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
        keep = inner if inner.mean() > 0.01 else med  # a tiny lit region (the beam) does not survive the erosion
        energy = energy * keep
        h, w = lum0.shape[0] // 5, lum0.shape[1] // 5
        y, x = best_window(energy, w, h)
        # one exposure per scene, from the plain ReSTIR crop's medium pixels: the no-reuse frame is sparse bright specks
        # at 1 spp, and an emitter in view would set it otherwise
        crop, cm = base[y:y + h, x:x + w], med[y:y + h, x:x + w]
        scale = np.percentile(crop[cm] if cm.sum() > 50 else crop, 99.5) + 1e-12
        for c, (cfg, title) in enumerate(GALLERY):
            ax = axes[r][c]
            ax.set_xticks([])
            ax.set_yticks([])
            for s in ax.spines.values():
                s.set_color(RULE)
            img = imgs.get(cfg)
            if img is None:
                ax.set_facecolor(SURFACE)
                ax.text(0.5, 0.5, "running", ha="center", va="center", color=INK2, transform=ax.transAxes)
            else:
                ax.imshow(tone(img[y:y + h, x:x + w, ::-1], scale), interpolation="nearest")
            if r == 0:
                ax.set_title(title, color=INK, fontsize=12)
            if c == 0:
                ax.set_ylabel(name, color=INK2, fontsize=10)
            cj = os.path.join(root, label, cfg, "c.corr.json")
            if os.path.exists(cj) and cfg != "noreuse":
                with open(cj) as fh:
                    d = json.load(fh)
                col = 0.5 * (d["color_rb"]["rho"]["8"] + d["color_gm"]["rho"]["8"])
                ax.set_xlabel("ρ̄ %.3f · colour %.3f" % (d["medium"]["rho"]["8"], col), color=INK2, fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=110, facecolor=SURFACE)
    plt.close(fig)


DENOISED = (("den_optix_c200_noreuse", "no reuse"), ("den_optix_c200_m0", "plain ReSTIR"), ("den_optix_c200_m1", "1 mutation"),
            ("den_optix_c200_m3", "3 mutations"), ("den_optix_c200_m10", "10 mutations"), ("ref", "reference"))
OPTIX_LABELS = ("bunnyswarm_d3", "bunnypinback_g0.97", "bunnypinback_g0.97_b2", "bunnyclosebox_b2")


def denoised_gallery_figure(root, out):
    """Per scene that needs more than one mutation: the OptiX output (first chain's first kept frame) of each config and
    the path-traced reference, cropped where plain ReSTIR's denoised error against the reference is largest inside the
    medium, one exposure per scene (from the reference). Under each: relMSE in the medium (equal_time_table.py's,
    mean over the kept frames)."""
    import artifacts as art
    import equal_time_table as et
    names = dict(LABELS)
    rows = [l for l in OPTIX_LABELS if os.path.exists(os.path.join(root, l, "den_optix_c200_m0", "c.corr.json"))]
    if not rows:
        return
    fig, axes = plt.subplots(len(rows), len(DENOISED), figsize=(3.3 * len(DENOISED), 2.35 * len(rows) + 0.4),
                             facecolor=SURFACE, squeeze=False)
    for r, label in enumerate(rows):
        ref = art.reference(root, label)
        imgs = {cfg: (art.kept_all(os.path.join(root, label, cfg)) or [None])[0] for cfg, _ in DENOISED if cfg != "ref"}
        imgs["ref"] = ref
        rel = et.scores(root, label, tuple(c for c, _ in DENOISED if c != "ref")) or {}
        mpath = os.path.join(root, label, "noreuse", "c.medium.npy")
        med = np.load(mpath) if os.path.exists(mpath) else np.ones(ref.shape[:2], bool)
        inner = cv2.erode(med.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
        lumw = np.array([0.2126, 0.7152, 0.0722])  # RGB
        err = cv2.GaussianBlur(np.abs((imgs["den_optix_c200_m0"] - ref) @ lumw), (0, 0), 3) * (inner if inner.mean() > 0.01 else med)
        h, w = ref.shape[0] // 4, ref.shape[1] // 4
        y, x = best_window(err, w, h)
        cm = med[y:y + h, x:x + w]
        rc = ref[y:y + h, x:x + w]
        scale = np.percentile(rc[cm] if cm.sum() > 50 else rc, 99.5) + 1e-12
        for c, (cfg, title) in enumerate(DENOISED):
            ax = axes[r][c]
            ax.set_xticks([])
            ax.set_yticks([])
            for s in ax.spines.values():
                s.set_color(RULE)
            img = imgs.get(cfg)
            if img is None:
                ax.set_facecolor(SURFACE)
            else:
                ax.imshow(tone(img[y:y + h, x:x + w], scale), interpolation="nearest")
            if r == 0:
                ax.set_title(title, color=INK, fontsize=12)
            if c == 0:
                ax.set_ylabel(names.get(label, label), color=INK2, fontsize=10)
            if cfg in rel:
                ax.set_xlabel("relMSE in the medium %.3f" % rel[cfg][0], color=INK2, fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=110, facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    root = sys.argv[1]
    os.makedirs(os.path.join(root, "figs"), exist_ok=True)
    curve_figure(root, os.path.join(root, "figs", "mutation_counts_curve.png"))
    gallery_figure(root, os.path.join(root, "figs", "mutation_counts_gallery.png"))
    denoised_gallery_figure(root, os.path.join(root, "figs", "mutation_counts_optix.png"))
    print("wrote figs/mutation_counts_curve.png, figs/mutation_counts_gallery.png, figs/mutation_counts_optix.png")
