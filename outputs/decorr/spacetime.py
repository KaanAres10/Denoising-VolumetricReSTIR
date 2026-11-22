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
                                 figs/spacetime.png (the (x, t) figure, after Junkins et al.'s Fig. 5)
    python spacetime.py <root> --night   the night street's at M cap 50 through every channel (spacetime_runs.py
                                 --night): figs/spacetime_night.png and five_denoisers/spacetime_night.json
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


SMAPE_EPS = 1e-4  # restir-eval's EPSILON


def smape(strip, ref, mask):
    """Junkins et al.'s error measure as their restir-eval computes it (compute_error_measures.smape): per pixel the
    mean over the frames of |s - r| / (|s| + |r| + 1e-4), in percent, on luminance (Rec. 709, as theirs); averaged
    over the band's medium. Unlike the relMSE it is not clipped."""
    s, r = strip @ mc.Y_RGB, ref @ mc.Y_RGB
    per_pixel = (np.abs(s - r) / (np.abs(s) + np.abs(r) + SMAPE_EPS)).mean(axis=0) * 100.0
    return float(per_pixel[mask].mean())


RELCOV_LAG = 3  # Junkins et al.'s lag T (their Eq. 17)


def relcov(strip, ref, mask, c0, lag=RELCOV_LAG):
    """Junkins et al.'s temporal covariance as their restir-eval computes it (compute_temporal_measures.relcov), at
    their lag of 3 frames: per pixel the covariance of its value with itself `lag` frames later over the product of
    its two means (each plus 1e-4), on unclipped Rec. 709 luminance, averaged over the band's medium. They take it
    over hundreds of independently seeded runs centred on their mean, which leaves the bias out; here it is over the
    frames of one run (strip, T x R x W x 3): centred on the reference, less the bias (the independent chain c0's error
    times the run's mean error, as stats), over the run's own means over the two spans of frames. The reference's value
    would not do as the mean: a denoiser smears the lamp into fog that is nearly black in it."""
    s, r = strip @ mc.Y_RGB, ref @ mc.Y_RGB
    e, e0 = s - r, c0 @ mc.Y_RGB - r
    cov = (e[:-lag] * e[lag:]).mean(axis=0) - e0 * e.mean(axis=0)
    return float((cov / ((s[:-lag].mean(axis=0) + SMAPE_EPS) * (s[lag:].mean(axis=0) + SMAPE_EPS)))[mask].mean())


def pick_window(err, width):
    """x0 of the `width`-pixel window of a band's error (R, W) with the largest total |error|."""
    a = np.nan_to_num(np.abs(err)).sum(axis=0)
    if width >= a.size:
        return 0
    c = np.concatenate([[0.0], np.cumsum(a)])
    return int(np.argmax(c[width:] - c[:-width]))


def scene(root, results, label, rows, width=WINDOW, configs=CONFIGS, pick=("c200", 0), ref_dir=None, within=None):
    """One setup's strips over the band `rows`: the reference's whole frame and display function, the `width`-pixel
    window where `pick`'s config (plain ReSTIR at M cap 200) with OptiX errs most on chain 0 (the paper crops'
    chain, as the band was chosen), inside the columns `within` if given, each of `configs`' statistics over the band
    (stats, against the same run's chain-0 capture: an independent chain) and the band's centre row in the window,
    frame by frame, and the reference's own error in the band (medium_metrics.own_relmse), part of every config's
    bias; and chain 0's error over the band as shown (err0: its displayed frame less the reference's, in the medium),
    by which the (x, t) figure picks its panels' pixels, so not where the display clips the error away. With
    ref_dir, the reference is that longer run's, though the display stays the setup's own reference's (the viewer's
    and the paper's exposure)."""
    import artifacts as art
    import five_figures as ff
    import five_scores
    import medium_metrics as mm
    y0, y1 = rows
    own = art.reference(root, label)
    if ref_dir:
        last = sorted(glob.glob(os.path.join(ref_dir, "c.Accum.output.*.exr")), key=lambda p: int(p.split(".")[-2]))[-1]
        ref = art.reference(root, label, override=last)
    else:
        ref, ref_dir = own, os.path.join(root, label, "ref")
    mask = np.load(os.path.join(root, label, "noreuse", "c.medium.npy"))
    rb, mb = ref[y0:y1], mask[y0:y1]
    band = np.zeros_like(mask)
    band[y0:y1] = mb
    run = os.path.join(root, results[label]["histories"][pick[0]]["m%d" % pick[1]]["optix"]["run"])
    chain0 = five_scores.frames(run, five_scores.channels(run)["optix"])[0][y0:y1]
    lo, hi = within or (0, ref.shape[1])
    x0 = lo + pick_window(error_field(chain0[None], rb, mb)[0][:, lo:hi], width)
    show = ff.display(label, own, mask)
    err0 = np.where(mb, np.abs(np.clip(show(chain0), 0, 1) - np.clip(show(rb), 0, 1)).mean(axis=-1), np.nan)
    x1, row = min(x0 + width, ref.shape[1]), (y1 - y0) // 2
    numbers, lines = {}, {}
    for den in CHANNELS:
        for hist, m in configs:
            path = find_strip(root, label, hist, m, den)
            if path is None:
                raise FileNotFoundError("no %s strip for %s %s m%d" % (den, label, hist, m))
            strip, run = np.load(path), os.path.dirname(path)
            c0 = five_scores.frames(run, five_scores.channels(run)[den])[0][y0:y1]
            numbers[den, hist, m] = dict(stats(error_field(strip, rb, mb), error_field(c0[None], rb, mb)[0]),
                                         smape=smape(strip, rb, mb), relcov_t3=relcov(strip, rb, mb, c0))
            lines[den, hist, m] = strip[:, row, x0:x1].astype(np.float64)
    return types.SimpleNamespace(frame=ref, rows=(y0, y1), cols=(x0, x1), ref_line=rb[row, x0:x1],
                                 inside=mb[row, x0:x1], lines=lines, numbers=numbers, err0=err0, show=show,
                                 ref_noise=mm.own_relmse(ref_dir, band))


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


# The page: the reference's whole frame with the strip marked, then five columns (the reference, and M cap 4, shipped,
# and M cap 200, each plain and with five mutations) and seven rows (the raw frame as rendered, then the difference of
# the raw frame and of each denoiser from the reference), x across and t down, in inches from the top left of a 7 in
# figure.
COLUMNS = (("reference", None, None), ("M cap 4 (shipped)\nplain", "ship", 0), ("M cap 4\n+ 5 mutations", "ship", 5),
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


# The (x, t) figure, after Junkins et al.'s Fig. 5: a block per setup, its name turned and a full-height cut of the
# reference's frame with the strip marked, then a row per channel (no denoiser, then each denoiser), each panel framed
# in its colour: the reference, then plain ReSTIR and five mutations at the shipped cap (4) and at M cap 200, the
# rendered row over the frames (x across, t down, square pixels); below, the error and the temporal correlation, one
# value a channel.
XT_DENOISERS = ("raw", "optix", "rr")
XT_COLUMNS = ((("Reference", ""), None, None), (("ReSTIR", "M cap 4 (shipped)"), "ship", 0),
              (("+ 5 mutations", "M cap 4"), "ship", 5), (("ReSTIR", "M cap 200"), "c200", 0),
              (("+ 5 mutations", "M cap 200"), "c200", 5))
XT_ROW_NAMES = {"raw": "No denoiser", "optix": "OptiX", "rr": "DLSS RR"}
# Junkins et al.'s panels (measured in their Fig. 5, 2026-11-01): 60 pixels across and 60 frames down, each pixel a
# square block. Ours: the 60 pixels of the window where chain 0 errs most, the strip's first 60 frames.
XT_N = 60
XT_PANEL = 0.56  # in, square: nine rows of them and their numbers fill a page
XT_NAME, XT_LABEL, XT_HEAD = 0.22, 0.2, 0.44
XT_ROW_GAP = 0.22  # under each row: the gap that holds its numbers
XT_KEY = "Under each panel: SMAPE · temporal correlation"
XT_HEAD_W = 0.99  # in: the widest column head, "+ 5 mutations" in 9 pt bold
XT_PITCH = 0.95  # in: the columns' least spacing, so that neighbouring heads (that and "ReSTIR") stand apart
# The dataviz palette's categorical slots 3-5 (after five_figures' BLUE and ORANGE, slots 1 and 2) for OIDN, NRD RELAX
# and NRD REBLUR: rows in slot order (OptiX, DLSS RR, then these) pass its adjacent-pair checks; REBLUR's magenta
# beside DLSS RR's orange would not.
AQUA, YELLOW, MAGENTA = "#1baf7a", "#eda100", "#e87ba4"

# The night street at M cap 50 (user-asked 2026-11-01, after the viewer's view of it through DLSS RR, plain against
# + 5 mutations, current shader): the (x, t) plot through every channel, against the 524k-spp reference (long_refs;
# its own reference is noisy there), each row's numbers under it. Its band and window lie in that view
# (spacetime_runs.NIGHT).
NIGHT_COLUMNS = ((("Reference", ""), None, None), (("ReSTIR", "M cap 50"), "c50", 0),
                 (("+ 5 mutations", "M cap 50"), "c50", 5))
NIGHT_CONFIGS = tuple((hist, m) for _, hist, m in NIGHT_COLUMNS if hist)
NIGHT_DENOISERS = ("raw", "optix", "rr", "oidn", "relax", "reblur")  # Figure 5's rows, then the rest in slot order
NIGHT_VIEW = (861, 1281)  # the view's columns in the frame
NIGHT_PANEL = 1.0  # in: one setup leaves room for larger blocks


def sub_window(cols, err, width):
    """The `width` columns of the window `cols` where the band's error `err` (R, W: chain 0's) is largest."""
    x0 = cols[0] + pick_window(err[:, cols[0]:cols[1]], width)
    return x0, min(x0 + width, cols[1])


def crop_around(shape, cols, aspect):
    """The columns (x0, x1) of a full-height cut of a frame of `shape` (H, W), `aspect` (width over height) wide,
    centred on the columns `cols` and kept inside the frame."""
    H, W = shape[:2]
    w = min(W, int(round(aspect * H)))
    x0 = int(round((cols[0] + cols[1]) / 2 - w / 2))
    x0 = max(0, min(x0, W - w))
    return x0, x0 + w


def _rho_cell(v):
    return "—" if v is None else "%.2f" % min(1.0, v)


def xt_canvas(scenes, dens, columns=XT_COLUMNS, panel=XT_PANEL, ink_names=False):
    """The setups in `scenes` (scene()'s, each with a `name`) as (x, t) plots of the rendered rows through each of
    `dens`, a block each (`columns` across, `dens` down), drawn as Junkins et al. draw theirs: square panels `panel`
    in wide, XT_N pixels across (sub_window: where chain 0 errs most in the window) by the strip's first XT_N frames
    down, each pixel a block; under each panel its SMAPE and temporal correlation (rho_t(3)), XT_KEY saying so once.
    ink_names: the rows named in ink, not in their colour (the hues past the second are under 3:1 on white, so there
    the name, not the hue, tells the rows apart)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.patheffects as pe
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    import five_figures as ff
    colours = {"raw": ff.MUTED, "optix": ff.BLUE, "rr": ff.ORANGE, "oidn": AQUA, "relax": YELLOW, "reblur": MAGENTA}
    T = min(XT_N, next(iter(scenes[0].lines.values())).shape[0])
    rows_h = len(dens) * panel + (len(dens) - 1) * XT_ROW_GAP
    pitch = max(panel + GAP, XT_PITCH)
    margin = max(0.04, (XT_HEAD_W - panel) / 2 + 0.02)  # the last column's head and 2 pt frame inside the page
    crop_w = ff.WIDTH - (XT_NAME + GAP + XT_LABEL + (len(columns) - 1) * pitch + panel) - margin
    px0 = XT_NAME + crop_w + GAP + XT_LABEL
    xs = [px0 + j * pitch for j in range(len(columns))]
    block = rows_h + XT_ROW_GAP + 0.15  # the panels, the last row's numbers and the gap to the next setup
    fig = plt.figure(figsize=(ff.WIDTH, XT_HEAD + len(scenes) * block - 0.15))
    for x, ((name, sub), _, _) in zip(xs, columns):
        ff._text(fig, x + panel / 2, 0.2, name, fontsize=9, fontweight="bold", ha="center", va="bottom")
        if sub:
            ff._text(fig, x + panel / 2, 0.38, sub, fontsize=7.5, color=ff.MUTED, ha="center", va="bottom")
    ff._text(fig, XT_NAME, 0.38, XT_KEY, fontsize=7, color=ff.MUTED, ha="left", va="bottom")
    halo = [pe.withStroke(linewidth=1.6, foreground=ff.INK)]
    for i, sc in enumerate(scenes):
        top = XT_HEAD + i * block
        x0, x1 = sub_window(sc.cols, sc.err0, XT_N)
        a, b = x0 - sc.cols[0], x1 - sc.cols[0]  # in the window's rows
        cx0, cx1 = crop_around(sc.frame.shape, (x0, x1), crop_w / rows_h)
        ax = ff._axes(fig, XT_NAME, top, crop_w, rows_h)
        ax.imshow(np.clip(sc.show(sc.frame[:, cx0:cx1]), 0, 1), aspect="auto")
        # the strip: exactly the pixels the panels show, one row (the band's middle), in a box white edged dark for
        # any sky; one row has no inside to see at this size, so the box reads as a line
        row = sc.rows[0] + (sc.rows[1] - sc.rows[0]) // 2
        ax.add_patch(Rectangle((x0 - cx0 - 0.5, row - 0.5), x1 - x0, 1, fill=False, edgecolor="white", lw=0.9,
                               path_effects=[pe.withStroke(linewidth=2.0, foreground=ff.INK)]))
        ax.set_xlim(-0.5, cx1 - cx0 - 0.5)
        ax.set_ylim(sc.frame.shape[0] - 0.5, -0.5)
        ff._cell(ax, "", 7)
        ff._text(fig, XT_NAME / 2, top + rows_h / 2, sc.name, fontsize=8.5, fontweight="bold", rotation=90,
                 ha="center", va="center")
        ref_img = np.clip(sc.show(np.broadcast_to(sc.ref_line[a:b], (T, b - a, 3))), 0, 1)
        for k, den in enumerate(dens):
            y = top + k * (panel + XT_ROW_GAP)
            colour = colours.get(den, ff.INK)
            ff._text(fig, px0 - XT_LABEL / 2, y + panel / 2, XT_ROW_NAMES.get(den, NAMES[den]), fontsize=7,
                     fontweight="bold", color=ff.INK if ink_names else colour, rotation=90, ha="center", va="center")
            for j, (x, (_, hist, m)) in enumerate(zip(xs, columns)):
                p = ff._axes(fig, x, y, panel, panel)
                img = ref_img if hist is None else np.clip(sc.show(sc.lines[den, hist, m][:T, a:b]), 0, 1)
                p.imshow(img, aspect="auto", interpolation="nearest")
                ff._cell(p, "", 7)
                for sp in p.spines.values():
                    sp.set_edgecolor(colour)
                    sp.set_linewidth(2.0)
                if i == 0 and k == 0 and j == 0:  # the axes, inside the first reference panel as in Junkins et al.
                    style = dict(arrowstyle="-|>", color="white", lw=1.2, path_effects=halo)
                    p.annotate("", xy=(0.93, 0.9), xytext=(0.05, 0.9), xycoords="axes fraction", arrowprops=style)
                    p.annotate("", xy=(0.05, 0.08), xytext=(0.05, 0.9), xycoords="axes fraction", arrowprops=style)
                    for s, (tx, ty) in (("$x$", (0.88, 0.74)), ("$t$", (0.14, 0.14))):
                        p.text(tx, ty, s, transform=p.transAxes, color="white", fontsize=9, ha="center",
                               va="center", path_effects=halo)
            for x, (_, hist, m) in zip(xs[1:], columns[1:]):  # the row's numbers, under its panels
                n = sc.numbers[den, hist, m]
                ff._text(fig, x + panel / 2, y + panel + 0.17, "%.1f · %s" % (n["smape"], _rho_cell(n["rho_t3"])),
                         fontsize=7, ha="center", va="bottom")
    return fig


def page_figure(sc, out):
    import matplotlib.pyplot as plt
    fig = page_canvas(sc.frame, sc.rows, sc.cols, sc.ref_line, sc.inside, sc.lines, sc.numbers, sc.show)
    fig.savefig(out, dpi=300, facecolor="white")
    plt.close(fig)


def xt_figure(scenes, dens, out, **kw):
    import matplotlib.pyplot as plt
    fig = xt_canvas(scenes, dens, **kw)
    fig.savefig(out, dpi=300, facecolor="white")
    plt.close(fig)


def summary(sc):
    """A setup's entry in the json: its band, window and frames, the reference's own error in the band and each
    config's statistics by history, mutations and channel."""
    hists = {}
    for (den, hist, m), s in sc.numbers.items():
        hists.setdefault(hist, {}).setdefault("m%d" % m, {})[den] = s
    return {"rows": list(sc.rows), "window": list(sc.cols), "frames": next(iter(sc.lines.values())).shape[0],
            "ref_noise": sc.ref_noise, "histories": hists}


def night(root, results, label, rows, view=NIGHT_VIEW):
    """The night street's (x, t) figure, figs/spacetime_night.png, and its numbers, five_denoisers/spacetime_night.json:
    NIGHT_COLUMNS through NIGHT_DENOISERS, the window where plain ReSTIR with OptiX errs most on chain 0 within the
    columns `view`."""
    import json
    import paper_tables
    sc = scene(root, results, label, rows, configs=NIGHT_CONFIGS, pick=NIGHT_CONFIGS[0],
               ref_dir=os.path.join(root, "long_refs", label, "ref"), within=view)
    sc.name = paper_tables.SETUP_NAMES.get(label, label)
    with open(os.path.join(root, "five_denoisers", "spacetime_night.json"), "w") as fh:
        json.dump({label: summary(sc)}, fh, indent=1)
    xt_figure([sc], NIGHT_DENOISERS, os.path.join(root, "figs", "spacetime_night.png"), columns=NIGHT_COLUMNS,
              panel=NIGHT_PANEL, ink_names=True)
    print(label, "window", sc.cols)


def main(argv=None, scenes=None):
    import argparse
    import json
    import paper_tables
    import spacetime_runs
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--results")
    ap.add_argument("--night", action="store_true")
    a = ap.parse_args(argv)
    with open(a.results or os.path.join(a.root, "five_denoisers", "results.json")) as fh:
        results = json.load(fh)
    if a.night:
        night(a.root, results, *next(iter(spacetime_runs.NIGHT.items())))
        return
    out, done = {}, []
    for label, rows in (scenes or spacetime_runs.SCENES).items():
        sc = scene(a.root, results, label, rows)
        sc.name = paper_tables.SETUP_NAMES.get(label, label)
        page_figure(sc, os.path.join(a.root, "figs", "spacetime_%s.png" % label))
        done.append(sc)
        out[label] = summary(sc)
        print(label, "window", sc.cols)
    with open(os.path.join(a.root, "five_denoisers", "spacetime.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    xt_figure(done, XT_DENOISERS, os.path.join(a.root, "figs", "spacetime.png"))


if __name__ == "__main__":
    main()
