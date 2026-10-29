"""Space-time strips, (x, t) plots after Junkins et al. (2026, Fig. 5), for three of the paper's setups
(spacetime_runs.py): one band of rows, frame after frame. A sample reuse shares across pixels is a horizontal blob; one
the history keeps is a vertical streak.

The error field is each strip's luminance error against the path-traced reference, clipped and scaled as the paper's
relMSE (medium_metrics.relmse), so the mean of its square over the band's medium is that band's relMSE. Its
statistics (stats) follow Junkins et al.'s Appendix A and their restir-eval code, which centre each pixel on its mean
over hundreds of independently seeded runs and so leave the bias out. Each config here has one run, so the bias is
taken from its other, independently seeded chain (the mean of that chain's error times the strip's mean error); the
rest is noise: the share of the error that is noise lasting the strip (still in it, yet not the other chain's), and
the noise's correlation with itself 1, 3, 10 and 30 frames later and with the pixels within 8, pooled over the band.

    python spacetime.py <root>   writes five_denoisers/spacetime.json, figs/spacetime_<setup>.png (a page each) and
                                 figs/spacetime.png (the overview)
"""
import glob
import os
import sys
import types

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_corr as mc  # noqa: E402

CONFIGS = (("ship", 0), ("ship", 5), ("c200", 0), ("c200", 5))  # (history, mutations)
CHANNELS = ("raw", "optix", "oidn", "relax", "reblur", "rr")
LAGS_T = (1, 3, 10, 30)
WINDOW = 320  # the (x, t) panels' width in pixels: their 128 frames down are 0.4 of it


def find_strip(root, label, hist, m, den):
    """The strip file of channel den for one config: the raw frame from the first of its runs, a denoiser from the run
    that carries it; None if there is none."""
    for d in sorted(glob.glob(os.path.join(root, label, "st_*_%s_m%d" % (hist, m)))):
        f = os.path.join(d, "c.strip.%s.npy" % den)
        if os.path.exists(f):
            return f
    return None


def error_field(strip, ref, mask):
    """(T, R, W) luminance error of a strip (T, R, W, 3) against the reference's band (R, W, 3), clipped and scaled as the
    paper's relMSE over the band's medium: the mean of its square there is that relMSE. NaN outside the medium."""
    lref = ref @ mc.Y_RGB
    cl = np.percentile(lref[mask], 99.5)
    scale = np.sqrt(max(np.mean(np.minimum(lref, cl)[mask] ** 2), 1e-20))
    e = (np.minimum(strip @ mc.Y_RGB, cl) - np.minimum(lref, cl)) / scale
    return np.where(mask, e, np.nan)


def pick_window(err, width):
    """x0 of the `width`-pixel window of a band's error (R, W) with the largest total |error|."""
    a = np.nan_to_num(np.abs(err)).sum(axis=0)
    if width >= a.size:
        return 0
    c = np.concatenate([[0.0], np.cumsum(a)])
    return int(np.argmax(c[width:] - c[:-width]))


def scene(root, results, label, rows, width=WINDOW):
    """One setup's strips over the band `rows`: the reference's whole frame and display function, the `width`-pixel
    window where plain ReSTIR with OptiX errs most on chain 0 at M cap 200 (the paper crops' chain, as the band was
    chosen), each config's statistics over the band (stats, against the same run's chain-0 capture: an independent
    chain) and the band's centre row in the window, frame by frame, and the reference's own error in the band
    (medium_metrics.own_relmse), part of every config's bias."""
    import artifacts as art
    import five_figures as ff
    import five_scores
    import medium_metrics as mm
    y0, y1 = rows
    ref = art.reference(root, label)
    mask = np.load(os.path.join(root, label, "noreuse", "c.medium.npy"))
    rb, mb = ref[y0:y1], mask[y0:y1]
    band = np.zeros_like(mask)
    band[y0:y1] = mb
    run = os.path.join(root, results[label]["histories"]["c200"]["m0"]["optix"]["run"])
    chain0 = five_scores.frames(run, five_scores.channels(run)["optix"])[0][y0:y1]
    x0 = pick_window(error_field(chain0[None], rb, mb)[0], width)
    x1, row = min(x0 + width, ref.shape[1]), (y1 - y0) // 2
    numbers, lines = {}, {}
    for den in CHANNELS:
        for hist, m in CONFIGS:
            path = find_strip(root, label, hist, m, den)
            if path is None:
                raise FileNotFoundError("no %s strip for %s %s m%d" % (den, label, hist, m))
            strip, run = np.load(path), os.path.dirname(path)
            c0 = five_scores.frames(run, five_scores.channels(run)[den])[0][y0:y1]
            numbers[den, hist, m] = stats(error_field(strip, rb, mb), error_field(c0[None], rb, mb)[0])
            lines[den, hist, m] = strip[:, row, x0:x1].astype(np.float64)
    return types.SimpleNamespace(frame=ref, rows=(y0, y1), cols=(x0, x1), ref_line=rb[row, x0:x1],
                                 inside=mb[row, x0:x1], lines=lines, numbers=numbers, show=ff.display(label, ref, mask),
                                 ref_noise=mm.own_relmse(os.path.join(root, label, "ref"), band))


def lasting(s):
    """The share of the error that is noise lasting the strip: standing still in it, but no other chain's. An estimate
    under zero (the bias's estimate has noise too) is none."""
    return max(0.0, s["static"] - s["bias"])


def numbers_line(s):
    """A panel's numbers: the relMSE, the noise that lasts, and the noise's correlation three frames later (within 1:
    an estimate over it errs by the bias estimate's own error)."""
    return "%.3f · %d%% · %s" % (s["energy"], round(100 * lasting(s)),
                                 "—" if s["rho_t3"] is None else "%.2f" % min(1.0, s["rho_t3"]))


RADIUS = 8  # the noise's neighbours: the disk Junkins et al. average over, and the paper's rho-bar(8)
NOISE_FLOOR = 0.2  # noise under this share of the error: the bias estimate's own error would swamp its correlations


def disk(radius):
    """The integer offsets (rows, columns) within `radius` of a pixel, less (0, 0)."""
    return [(i, j) for i in range(-radius, radius + 1) for j in range(-radius, radius + 1)
            if (i, j) != (0, 0) and i * i + j * j <= radius * radius]


def stats(e, c0, lags=LAGS_T, radius=RADIUS):
    """Over the medium of a strip's error field e (T, R, W), with c0 (R, W) the error of an independent chain at the
    same pixels: the energy (the mean square, a relMSE); the share of it that is bias (what independent chains share:
    the mean of c0 times e's mean over the frames, as their noise is independent); the share that stands still over
    the frames (each pixel's mean, squared: the bias and the noise that lasts the strip); and of the noise (the error
    less the bias) its correlation with itself `lags` frames later and its mean correlation with the pixels within
    `radius`, pooled over the pixels. Junkins et al.'s measures, but centred on one other chain rather than the mean
    of many runs, and pooled rather than averaged per pixel; None where the noise is under NOISE_FLOOR of the error."""
    inside = ~np.isnan(e[0]) & ~np.isnan(c0)
    T, n = len(e), max(int(inside.sum()), 1)
    z, z0 = np.where(inside, e, 0.0), np.where(inside, c0, 0.0)  # zero outside the medium, so products count inside
    zb = z.mean(axis=0)
    energy = float(np.einsum("thw,thw->", z, z) / (n * T))
    bias = float((z0 * zb).sum() / n)
    out = {"energy": energy, "static": float((zb ** 2).sum() / n) / energy if energy > 0 else 0.0,
           "bias": bias / energy if energy > 0 else 0.0}
    noise = energy - bias
    ok = energy > 0 and noise > NOISE_FLOOR * energy
    for tau in (t for t in lags if t < T):
        lagged = float(np.einsum("thw,thw->", z[:-tau], z[tau:]) / (n * (T - tau)))
        out["rho_t%d" % tau] = (lagged - bias) / noise if ok else None
    out["rho_s%d" % radius] = None
    if not ok:
        return out
    H, W = inside.shape
    m, q, own = inside.astype(np.float64), (z ** 2).sum(axis=0), z0 * zb  # per pixel: its sum of squares, its bias
    near = []
    for di, dj in disk(radius):
        if abs(di) >= H or abs(dj) >= W:  # no pixel pairs this far apart in the band (a slice would wrap round)
            continue
        a = (slice(max(0, -di), min(H, H - di)), slice(max(0, -dj), min(W, W - dj)))
        b = (slice(max(0, di), min(H, H + di)), slice(max(0, dj), min(W, W + dj)))
        pairs = m[a] * m[b]
        k = pairs.sum()
        if k == 0:
            continue
        cov = (np.einsum("thw,thw->", z[:, a[0], a[1]], z[:, b[0], b[1]]) / (k * T)
               - 0.5 * ((z0[a] * zb[b] + zb[a] * z0[b]) * pairs).sum() / k)
        va = (q[a] * m[b]).sum() / (k * T) - (own[a] * pairs).sum() / k
        vb = (q[b] * m[a]).sum() / (k * T) - (own[b] * pairs).sum() / k
        if va > 0 and vb > 0:
            near.append(cov / np.sqrt(va * vb))
    out["rho_s%d" % radius] = float(np.mean(near)) if near else None
    return out


# The page: the reference's whole frame with the strip marked, then five columns (the reference, and the shipped cap
# and M cap 200, each plain and with five mutations) and seven rows (the raw frame as rendered, then the difference of
# the raw frame and of each denoiser from the reference), x across and t down, in inches from the top left of a 7 in
# figure.
COLUMNS = (("reference", None, None), ("shipped cap\nplain", "ship", 0), ("shipped cap\n+ 5 mutations", "ship", 5),
           ("M cap 200\nplain", "c200", 0), ("M cap 200\n+ 5 mutations", "c200", 5))
ROWS = (("raw", "image"), ("raw", "error"), ("optix", "error"), ("oidn", "error"), ("relax", "error"),
        ("reblur", "error"), ("rr", "error"))
NAMES = {"raw": "raw frame", "optix": "OptiX", "oidn": "OIDN", "relax": "NRD RELAX", "reblur": "NRD REBLUR",
         "rr": "DLSS RR"}
LABEL, GAP, BAND = 0.8, 0.06, 1.45
GAIN_TOP = 0.45  # a row's amplification puts its plain M cap 200 difference's 99th percentile this far from grey
KEY = ("Each panel: one row of the strip (orange) across, %d consecutive frames down. A vertical streak is an error "
       "that stays from frame to frame; a horizontal blob, one that neighbours share; fine noise, neither. Difference "
       "panels: the frame minus the reference, amplified (row label), on grey. Above each, in the band's medium: the "
       "relative MSE, the share of the error that is noise lasting all %d frames (still, yet not shared by an "
       "independent chain, so not bias), and the noise's correlation with itself three frames later.")
SWATCHES = (("right", (0.5, 0.5, 0.5)), ("too bright", (0.8, 0.8, 0.8)), ("too dark", (0.2, 0.2, 0.2)),
            ("too red", (0.8, 0.35, 0.35)))


def difference(img, ref_img, gain):
    """A rendered strip's difference from the reference's in display space, on grey: grey where right, tinted where
    the colour is wrong, lighter or darker where too bright or too dark."""
    return np.clip(0.5 + gain * (img - ref_img), 0, 1)


def gain(img, ref_img, inside):
    """A row's amplification, whole: the 99th percentile of |img - ref_img| over the medium's columns to GAIN_TOP."""
    d = np.abs(img - ref_img)[:, inside]
    return max(1, int(round(GAIN_TOP / max(float(np.percentile(d, 99)), 1e-6))))


def page_canvas(frame, rows, cols, ref_line, inside, lines, numbers, show):
    """One setup's page. frame: the reference's whole frame; rows, cols: the strip's band and the window shown;
    ref_line, inside: the reference's row the panels show, in the window (w, 3), and its medium (w,); lines
    {(channel, history, mutations): that row over the frames (T, w, 3)}; numbers: their statistics over the band (stats);
    show: the setup's display function."""
    import textwrap
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    import five_figures as ff
    (y0, y1), (x0, x1) = rows, cols
    T, w = next(iter(lines.values())).shape[:2]
    cw = (ff.WIDTH - LABEL - 4 * GAP) / 5
    ph = cw * T / w
    top = 0.24 + BAND + 0.42
    fig = plt.figure(figsize=(ff.WIDTH, top + 0.06 + ph + (len(ROWS) - 1) * (0.17 + ph) + 0.03))
    wide = BAND * frame.shape[1] / frame.shape[0]
    ax = ff._axes(fig, LABEL, 0.24, wide, BAND)
    ax.imshow(np.clip(show(frame), 0, 1))
    ax.add_patch(Rectangle((x0 - 0.5, y0 - 0.5), x1 - x0, y1 - y0, fill=False, ec=ff.ORANGE, lw=1.4))
    ff._cell(ax, "", 8)
    ff._text(fig, LABEL + wide / 2, 0.19, "reference, whole frame: the strip", fontsize=8.5, fontweight="bold",
             ha="center", va="bottom")
    ff._text(fig, LABEL + wide + 0.2, 0.26, textwrap.fill(KEY % (T, T), 62), fontsize=7, color=ff.MUTED, ha="left",
             va="top", linespacing=1.35)
    ref_img = np.clip(show(np.broadcast_to(ref_line, (T,) + ref_line.shape)), 0, 1)
    for j, (name, _, _) in enumerate(COLUMNS):
        ff._text(fig, LABEL + j * (cw + GAP) + cw / 2, top, name, fontsize=8, fontweight="bold", ha="center",
                 va="bottom", linespacing=1.1)
    yy = top + 0.06
    for den, kind in ROWS:
        imgs = {(hist, m): np.clip(show(lines[den, hist, m]), 0, 1) for _, hist, m in COLUMNS if hist}
        g = gain(imgs["c200", 0], ref_img, inside) if kind == "error" else 1
        for j, (_, hist, m) in enumerate(COLUMNS):
            x = LABEL + j * (cw + GAP)
            if hist is None:
                if kind == "image":
                    a = ff._axes(fig, x, yy, cw, ph)
                    a.imshow(ref_img, aspect="auto", interpolation="nearest")
                    ff._cell(a, "", 7)
                elif den == "raw":  # the first difference row's reference cell: the key to the differences
                    for i, (word, rgb) in enumerate(SWATCHES):
                        a = ff._axes(fig, x + 0.1, yy + 0.04 + i * 0.16, 0.11, 0.11)
                        a.imshow(np.ones((1, 1, 3)) * rgb)
                        ff._cell(a, "", 6)
                        ff._text(fig, x + 0.27, yy + 0.095 + i * 0.16, word, fontsize=7, va="center")
                continue
            a = ff._axes(fig, x, yy, cw, ph)
            a.imshow(imgs[hist, m] if kind == "image" else difference(imgs[hist, m], ref_img, g), aspect="auto",
                     interpolation="nearest")
            ff._cell(a, "", 7)
            if kind == "error":
                ff._text(fig, x + cw / 2, yy - 0.025, numbers_line(numbers[den, hist, m]), fontsize=6.5, ha="center",
                         va="bottom")
        label = NAMES[den] if kind == "image" else "%s\ndifference ×%d" % (NAMES[den], g)
        ff._text(fig, LABEL - 0.08, yy + ph / 2, label, fontsize=7.5, ha="right", va="center", linespacing=1.1)
        yy += ph + 0.17
    return fig


# The overview: one block per setup, the reference's whole frame with the strip at its left, then the raw frame's and
# one denoiser's difference at the shipped cap and at M cap 200, plain and with five mutations, over the middle
# OVERVIEW pixels of the page's window (square pixels in x and t, as on the pages).
OVERVIEW = 160
OVERVIEW_DENOISER = "optix"  # frame by frame: what persists in its output came in with its input
STEPS = (("shipped cap\nplain", "ship", 0), ("M cap 200\nplain", "c200", 0), ("M cap 200\n+ 5 mutations", "c200", 5))
THUMB, GROUP = 1.25, 0.14


def middle(cols, width):
    """The middle `width` columns of the window `cols`."""
    x0 = cols[0] + max(0, (cols[1] - cols[0] - width) // 2)
    return x0, min(x0 + width, cols[1])


def overview_canvas(scenes, den, width=OVERVIEW):
    """The setups in `scenes` (scene()'s, each with a `name`) one block each: the whole frame with the strip, then the
    raw frame's and `den`'s differences from the reference at STEPS over the middle `width` pixels of the page's
    window, each channel amplified alike on every setup (the median of their pages' amplifications)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    import five_figures as ff
    T = next(iter(scenes[0].lines.values())).shape[0]
    cw = (ff.WIDTH - THUMB - 0.12 - GROUP - 4 * GAP) / 6
    ph = cw * T / width
    views = []
    for sc in scenes:
        a, b = (c - sc.cols[0] for c in middle(sc.cols, width))
        ref_img = np.clip(sc.show(np.broadcast_to(sc.ref_line[a:b], (T, b - a, 3))), 0, 1)
        imgs = {(ch, hist, m): np.clip(sc.show(sc.lines[ch, hist, m][:, a:b]), 0, 1)
                for ch in ("raw", den) for _, hist, m in STEPS}
        views.append((sc, a, b, ref_img, imgs))
    g = {ch: max(1, int(round(float(np.median([gain(v[4][ch, "c200", 0], v[3], v[0].inside[v[1]:v[2]])
                                                for v in views]))))) for ch in ("raw", den)}
    head = 0.5
    fig = plt.figure(figsize=(ff.WIDTH, head + len(scenes) * (0.16 + ph + 0.1)))
    xs = [THUMB + 0.12 + j * (cw + GAP) + (GROUP - GAP if j >= 3 else 0.0) for j in range(6)]
    for k, ch in enumerate(("raw", den)):
        x = xs[3 * k] + (3 * cw + 2 * GAP) / 2
        ff._text(fig, x, 0.15, "%s: difference ×%d" % (NAMES[ch], g[ch]), fontsize=8.5, fontweight="bold",
                 ha="center", va="bottom")
        for j, (name, _, _) in enumerate(STEPS):
            ff._text(fig, xs[3 * k + j] + cw / 2, 0.44, name, fontsize=7.5, ha="center", va="bottom",
                     linespacing=1.05)
    for i, (sc, a, b, ref_img, imgs) in enumerate(views):
        top = head + i * (0.16 + ph + 0.1)
        th = min(ph, THUMB * sc.frame.shape[0] / sc.frame.shape[1])
        ax = ff._axes(fig, 0.0, top + 0.16, th * sc.frame.shape[1] / sc.frame.shape[0], th)
        ax.imshow(np.clip(sc.show(sc.frame), 0, 1))
        (y0, y1), (x0, _) = sc.rows, sc.cols
        ax.add_patch(Rectangle((x0 + a - 0.5, y0 - 0.5), b - a, y1 - y0, fill=False, ec=ff.ORANGE, lw=1.0))
        ff._cell(ax, "", 7)
        ff._text(fig, 0.0, top + 0.12, sc.name, fontsize=7.5, fontweight="bold", ha="left", va="bottom")
        for k, ch in enumerate(("raw", den)):
            for j, (_, hist, m) in enumerate(STEPS):
                x = xs[3 * k + j]
                p = ff._axes(fig, x, top + 0.16, cw, ph)
                p.imshow(difference(imgs[ch, hist, m], ref_img, g[ch]), aspect="auto", interpolation="nearest")
                ff._cell(p, "", 7)
                ff._text(fig, x + cw / 2, top + 0.13, numbers_line(sc.numbers[ch, hist, m]), fontsize=6.3,
                         ha="center", va="bottom")
    return fig


def page_figure(sc, out):
    import matplotlib.pyplot as plt
    fig = page_canvas(sc.frame, sc.rows, sc.cols, sc.ref_line, sc.inside, sc.lines, sc.numbers, sc.show)
    fig.savefig(out, dpi=300, facecolor="white")
    plt.close(fig)


def overview_figure(scenes, den, out):
    import matplotlib.pyplot as plt
    fig = overview_canvas(scenes, den)
    fig.savefig(out, dpi=300, facecolor="white")
    plt.close(fig)


def main(argv=None, scenes=None):
    import argparse
    import json
    import paper_tables
    import spacetime_runs
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--results")
    a = ap.parse_args(argv)
    with open(a.results or os.path.join(a.root, "five_denoisers", "results.json")) as fh:
        results = json.load(fh)
    out, done = {}, []
    for label, rows in (scenes or spacetime_runs.SCENES).items():
        sc = scene(a.root, results, label, rows)
        sc.name = paper_tables.SETUP_NAMES.get(label, label)
        page_figure(sc, os.path.join(a.root, "figs", "spacetime_%s.png" % label))
        done.append(sc)
        hists = {}
        for (den, hist, m), s in sc.numbers.items():
            hists.setdefault(hist, {}).setdefault("m%d" % m, {})[den] = s
        out[label] = {"rows": list(sc.rows), "window": list(sc.cols), "frames": next(iter(sc.lines.values())).shape[0],
                      "ref_noise": sc.ref_noise, "histories": hists}
        print(label, "window", sc.cols)
    with open(os.path.join(a.root, "five_denoisers", "spacetime.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    overview_figure(done, OVERVIEW_DENOISER, os.path.join(a.root, "figs", "spacetime.png"))


if __name__ == "__main__":
    main()
