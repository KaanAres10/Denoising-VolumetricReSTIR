"""run_film.sh's figures (spec V-C7): per real-world shot, figs/film_<label>.png -- raw, OptiX and Ray Reconstruction
without reuse and with 0, 1, 3 and 10 mutations at M cap 200, each denoiser's brightness error against the reference
beneath it (and RR's with its overall brightness matched to the reference's), the reference on the right with the whole
shot (crop boxed) and the reference's own noise; the crop goes where plain ReSTIR's OptiX error is largest inside the
medium. Every score is equal_time_table's in-medium relMSE, the mean of the two kept frames (separate chains) with
their range. figs/film_summary.png: those scores against the count, one line per shot, OptiX and RR side by side.

    python film_figures.py <outputs/decorr> [labels...]
"""
import glob
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import matplotlib  # noqa: E402
import matplotlib.ticker  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art  # noqa: E402
import counts_figures as cf  # noqa: E402
import paper_figure as pf  # noqa: E402

SHOTS = (("plumerig_g0.6", "concert lighting rig in stage haze"), ("plumewall_g0.6_d0.3", "LED video wall behind thin haze"),
         ("wdasstorm_g0.5", "night thunderstorm over a city"), ("emeraldneon_d3", "neon street in fog"),
         ("stage_g0.6", "concert stage in haze"), ("lanterns_g0.5", "sky lanterns over ground mist"),
         ("fireworks_g0.4", "fireworks over a city square"), ("wdasdusk_g0.6", "storm at dusk"))
COUNTS = (0, 1, 3, 10)
LUM = np.array([0.2126, 0.7152, 0.0722])  # RGB (artifacts' frames are RGB)
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
EXPOSURE_KEY = 0.3  # the crop's median medium brightness lands at t = 0.3, a quarter of white


def exposure(v, med):
    """The exposure for a crop: the median of its medium's brightness (display's brightest channel) / EXPOSURE_KEY. A
    lightning flash filling a fifth of the crop leaves the median where it was, where a high percentile pushes the rest
    of the storm to black."""
    v = v[med] if med.sum() > 50 else v.ravel()
    v = v[v > 0]
    return float(np.median(v)) / EXPOSURE_KEY if v.size else 1.0


def display(img, k):
    """Reinhard's t / (1 + t) on each pixel's brightest channel (t = it / k), the pixel scaled with it: nothing clips,
    so a flash keeps its shading, and a light far above the exposure (an LED tile, a neon sign) keeps its own hue
    instead of going white."""
    v = img.max(-1)
    t = np.clip(v / k, 0, None)
    out = img * ((t / (1 + t)) / np.maximum(v, 1e-12))[..., None]
    return np.clip(out, 0, 1) ** (1 / 2.2)


def cfg_name(prefix, n):
    """Config name: raw configs have no prefix; n None = no reuse."""
    if n is None:
        return prefix + "c200_noreuse" if prefix else "noreuse"
    return "%sc200_m%d" % (prefix, n)


def half_reference_path(root, label):
    """The reference's first accumulation (half its frames), or None when only one is on disk."""
    refs = sorted(glob.glob(os.path.join(root, label, "ref", "c.Accum.output.*.exr")), key=lambda p: int(p.split(".")[-2]))
    return refs[0] if len(refs) >= 2 else None


def noise_floor(relmse, half):
    """The reference's own share of every score: relMSE of its first half against the whole. With independent frames
    half - whole = (first half - second half) / 2, whose variance is the whole mean's, so this estimates the whole
    reference's error against the truth; the render's error being independent of it, each score is the render's
    relMSE plus this."""
    return relmse(half)


def score_label(rels, ratio):
    return "relMSE %.3f (%.3f-%.3f) · mean %.2fx" % (np.mean(rels), min(rels), max(rels), ratio)


def scene_figure(root, label, name, out):
    """Draws figs/film_<label>.png; returns ({(prefix, n): (per-chain relMSE, mean ratio)}, reference noise floor)."""
    d0 = os.path.join(root, label)
    if not os.path.exists(os.path.join(d0, "ref", "c.schedule.json")):
        return None
    p = pf.prepare(root, label, cfg_name("", None), cfg_name("", 0))  # equal_time_table's in-medium relMSE
    half = half_reference_path(root, label)
    floor = noise_floor(p.relmse, art.reference(root, label, override=half)[p.crop]) if half else None
    ref = art.reference(root, label)
    ref_y = ref @ LUM
    med = np.load(os.path.join(d0, "noreuse", "c.medium.npy")) if os.path.exists(os.path.join(d0, "noreuse", "c.medium.npy")) \
        else ref_y > 0.02 * np.percentile(ref_y, 99.5)
    g = lambda a: cv2.GaussianBlur(np.where(med, a, 0.0), (0, 0), 1.5) / np.maximum(cv2.GaussianBlur(med.astype(float), (0, 0), 1.5), 1e-3)  # noqa: E731
    gr = g(ref_y)
    ok = med & (gr > 0)
    err = lambda img: np.where(ok, np.log(np.maximum(g(img @ LUM), 1e-9) / np.where(ok, gr, 1)), np.nan)  # noqa: E731
    # the crop: where plain ReSTIR's OptiX output is furthest from the reference inside the medium
    base = (art.kept_all(os.path.join(d0, cfg_name("den_optix_", 0))) or [None])[0]
    h, w = ref.shape[0] // 3, ref.shape[1] // 3
    if base is not None:
        e = np.nan_to_num(np.abs(err(base)))
        y, x = cf.best_window(cv2.GaussianBlur(e, (0, 0), 3), w, h)
    else:
        y, x = (ref.shape[0] - h) // 2, (ref.shape[1] - w) // 2
    sl = (slice(y, y + h), slice(x, x + w))
    k = exposure(ref[sl].max(-1), med[sl])
    show = lambda img: display(img, k)  # noqa: E731
    ref_mean = (p.ref @ LUM)[p.inside].mean()
    cols = [("no reuse", None)] + [("plain ReSTIR" if n == 0 else "%d mutation%s" % (n, "" if n == 1 else "s"), n) for n in COUNTS] \
        + [("reference", "ref")]
    rows = (("raw frame", "", "img"), ("OptiX", "den_optix_", "img"), ("OptiX error", "den_optix_", "err"),
            ("Ray Reconstruction", "den_rr_", "img"), ("RR error", "den_rr_", "err"), ("RR error, mean matched", "den_rr_", "matched"))
    scores = {}
    fig, axes = plt.subplots(len(rows), len(cols), figsize=(3.0 * len(cols), 1.9 * len(rows) + 0.6), facecolor="#fcfcfb", squeeze=False)
    for c_, (cname, n) in enumerate(cols):
        for r_, (rname, prefix, kind) in enumerate(rows):
            ax = axes[r_][c_]
            ax.set_xticks([]); ax.set_yticks([])
            if r_ == 0:
                ax.set_title(cname, fontsize=11)
            if c_ == 0:
                ax.set_ylabel(rname, fontsize=9, color="#52514e")
            if n == "ref":
                if kind == "img":
                    ax.imshow(show(ref[sl]), interpolation="nearest")
                elif r_ == 2:
                    ax.imshow(show(ref), interpolation="lanczos")
                    ax.add_patch(Rectangle((x - 0.5, y - 0.5), w, h, fill=False, edgecolor="#eda100", linewidth=1.5))
                    ax.set_xlabel("the whole shot, crop boxed", fontsize=8, color="#52514e")
                elif r_ == 4 and floor is not None:
                    ax.axis("off")
                    ax.text(0.5, 0.5, "the reference's own noise:\nrelMSE %.4f of each score" % floor, ha="center", va="center",
                            transform=ax.transAxes, color="#52514e", fontsize=9)
                else:
                    ax.axis("off")
                continue
            cfg = cfg_name(prefix, n)
            d = os.path.join(d0, cfg)
            if not os.path.exists(os.path.join(d, "c.corr.json")):
                ax.text(0.5, 0.5, "running", ha="center", va="center", transform=ax.transAxes, color="#52514e", fontsize=9)
                continue
            frames = art.kept_all(d)
            if not frames:
                continue
            img = frames[0]
            if kind == "img":
                ax.imshow(show(img[sl]), interpolation="nearest")
                if prefix:
                    rels = [p.relmse(f[p.crop]) for f in frames]
                    ratio = float(np.mean([(f[p.crop] @ LUM)[p.inside].mean() for f in frames]) / max(ref_mean, 1e-12))
                    scores[(prefix, n)] = (rels, ratio)
                    ax.set_xlabel(score_label(rels, ratio), fontsize=8, color="#52514e")
            else:
                ratio = (img @ LUM)[med].mean() / max(ref_y[med].mean(), 1e-12)  # the shown frame's own brightness
                e = err(img / ratio) if kind == "matched" else err(img)
                ax.imshow(e[sl], cmap="RdBu_r", vmin=-0.8, vmax=0.8, interpolation="nearest")
    fig.suptitle("%s (%s), M cap 200: red too bright, blue too dark against the reference" % (name, label), fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(out, dpi=90, facecolor="#fcfcfb")
    plt.close(fig)
    return scores, floor


def summary_sets(results):
    """[(file name, shots)]: one summary per run of four SHOTS (one colour each, never cycled), holding those rendered."""
    sets = []
    for i in range(0, len(SHOTS), len(SERIES)):
        shots = [s for s in SHOTS[i:i + len(SERIES)] if s[0] in results]
        if shots:
            sets.append(("film_summary.png" if i == 0 else "film_summary_%d.png" % (i // len(SERIES) + 1), shots))
    return sets


def summary_figure(results, out, shots):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), facecolor="#fcfcfb")
    xs = {None: 0, **{n: i + 1 for i, n in enumerate(COUNTS)}}
    floored = []
    for ax, (prefix, title) in zip(axes, (("den_optix_", "OptiX"), ("den_rr_", "Ray Reconstruction"))):
        ax.set_facecolor("#fcfcfb")
        for (label, name), col in zip(shots, SERIES):
            s, floor = results.get(label) or ({}, None)
            ns = [n for n in COUNTS if (prefix, n) in s]
            for n in ([None] if (prefix, None) in s else []) + ns:  # the two chains' range
                rels = s[(prefix, n)][0]
                ax.plot([xs[n]] * 2, [min(rels), max(rels)], color=col, linewidth=1, alpha=0.6)
            if ns:
                ax.plot([xs[n] for n in ns], [np.mean(s[(prefix, n)][0]) for n in ns], color=col, linewidth=2, marker="o",
                        markersize=8, markeredgecolor="#fcfcfb", markeredgewidth=2, label=name)
            if (prefix, None) in s:  # no reuse: its own point, not on the line
                ax.plot([0], [np.mean(s[(prefix, None)][0])], linestyle="none", marker="o", markersize=8,
                        markerfacecolor="#fcfcfb", markeredgecolor=col, markeredgewidth=2)
            lo = min([np.mean(v[0]) for v in s.values()] or [1])
            if floor is not None and floor > 0.25 * lo:  # the reference's noise is a visible share of the scores
                ax.axhline(floor, color=col, linewidth=1, linestyle=":")
                if name not in floored:
                    floored.append(name)
        ax.set_xticks(range(len(COUNTS) + 1), ["no reuse"] + [str(n) for n in COUNTS])
        # log: the scores span 0.015-0.26, and a count's effect is a ratio
        ax.set_yscale("log")
        ticks = (0.015, 0.02, 0.03, 0.05, 0.1, 0.2)
        ax.yaxis.set_major_locator(matplotlib.ticker.FixedLocator(ticks))
        ax.yaxis.set_major_formatter(matplotlib.ticker.FixedFormatter([str(t) for t in ticks]))
        ax.yaxis.set_minor_locator(matplotlib.ticker.NullLocator())
        for s_ in ("top", "right"):
            ax.spines[s_].set_visible(False)
        ax.yaxis.grid(True, color="#ebeae5")
        ax.set_xlabel("mutations per pixel per frame (M cap 200)", color="#52514e")
        ax.set_title(title + ": relMSE in the medium against the reference", loc="left", fontsize=11)
    axes[0].legend(frameon=False, fontsize=9)
    note = "dots: mean of two frames, bar: their range; hollow: no reuse"
    if floored:
        note += "; dotted: the reference's own noise (%s)" % ", ".join(floored)
    fig.text(0.01, 0.01, note, fontsize=9, color="#52514e")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=110, facecolor="#fcfcfb")
    plt.close(fig)


def main(argv):
    root = argv[1]
    want = set(argv[2:])
    os.makedirs(os.path.join(root, "figs"), exist_ok=True)
    results = {}
    for label, name in SHOTS:
        if want and label not in want:
            continue
        r = scene_figure(root, label, name, os.path.join(root, "figs", "film_%s.png" % label))
        if r is None:
            print("%s: no reference yet" % label)
            continue
        results[label] = r
        s, floor = r
        print("%-22s reference noise %s" % (label, "%.4f" % floor if floor is not None else "-"))
        for prefix in ("den_optix_", "den_rr_"):
            row = ["%s: %.4f (%.4f-%.4f, %.2fx)" % ("noreuse" if n is None else n, np.mean(s[(prefix, n)][0]), min(s[(prefix, n)][0]),
                                                    max(s[(prefix, n)][0]), s[(prefix, n)][1])
                   for n in (None,) + COUNTS if (prefix, n) in s]
            print("    %-6s %s" % (prefix[4:-1], "  ".join(row)))
    for name, shots in summary_sets(results):
        summary_figure(results, os.path.join(root, "figs", name), shots)


if __name__ == "__main__":
    main(sys.argv)
