"""The paper's new figures (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E6) from run_five.sh's runs
and five_scores.py's results:
- a page per setup: the path-traced reference across the top (the whole frame with the box where plain ReSTIR +
  OptiX errs most, and that box enlarged), then each denoiser's crop before and after 5 mutations and each one's
  signed error against the reference;
- the teaser: the setup whose median cut over the five denoisers at M cap 200 is largest, as its page without the
  crops' two rows;
- the cover (the paper's first figure and the project page's): COVER's setup through one denoiser, plain, + 5
  mutations and the reference, the whole medium on top and a zoom below; and a two-column version for phones;
- the strip: STRIP's setups, the teaser's first two rows one row each;
- the history chart: per denoiser, each setup's denoised relMSE with mutations over without, at the shipped cap and
  at M cap 200; and M cap 200 with mutations over plain ReSTIR at the shipped cap.

    python five_figures.py <root> [--results <root>/five_denoisers/results.json]
"""
import argparse
import json
import os
import sys
import textwrap
import types

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art  # noqa: E402
import five_runs  # noqa: E402
import five_scores  # noqa: E402
import m_corr as mc  # noqa: E402
import paper_figure  # noqa: E402
import paper_tables  # noqa: E402
from variety_figures import EXPOSURE, PAPER_DISPLAY  # noqa: E402

DENOISERS = ("optix", "oidn", "relax", "reblur", "rr")
NAMES = {"optix": "OptiX", "oidn": "OIDN", "relax": "NRD RELAX", "reblur": "NRD REBLUR", "rr": "DLSS RR"}
STRIP = ["bunnycathedral_d0.3", "bunnylanterns", "explosiondusk_b2", "bunnyswarm_d3"]
# dataviz reference palette, light mode: categorical slots 1 and 2 (validated all-pairs), text and recessive ink.
BLUE, ORANGE, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#d9d8d4"
OUTSIDE = "#bdbcb8"  # the error maps outside the medium: darker than RdBu's near-white zero, so not read as no error


def cut(results, label, hist, den):
    c = results[label]["histories"][hist]
    return 1.0 - c["m5"][den]["mean"] / c["m0"][den]["mean"]


def complete(results, label, hist="c200"):
    c = results[label]["histories"].get(hist, {})
    return all(den in c.get(m, {}) for m in ("m0", "m5") for den in DENOISERS)


def teaser_setup(results):
    ok = [label for label in results if complete(results, label)]
    return max(ok, key=lambda label: float(np.median([cut(results, label, "c200", d) for d in DENOISERS])))


def _frame(root, results, label, hist, m, den):
    run = os.path.join(root, results[label]["histories"][hist]["m%d" % m][den]["run"])
    return five_scores.frames(run, five_scores.channels(run)[den])[0]  # chain 0's capture


def panel(root, results, label, hist="c200"):
    """Before/after per denoiser (chain 0), the reference, the medium, the zoom box and the display function."""
    ref = art.reference(root, label)
    mask = np.load(os.path.join(root, label, "noreuse", "c.medium.npy"))
    imgs = {d: (_frame(root, results, label, hist, 0, d), _frame(root, results, label, hist, 5, d)) for d in DENOISERS}
    size = max(64, min(ref.shape[:2]) // 5)
    (y, x), = paper_figure.pick_boxes(imgs["optix"][0], ref, size, n=1, mask=mask)
    if label in PAPER_DISPLAY:
        show = art.srgb_display
    else:
        k = np.percentile((ref @ mc.Y_RGB)[mask], EXPOSURE.get(label, 99.0)) + 1e-9
        show = lambda img: art.tonemap(img, k)  # noqa: E731
    return types.SimpleNamespace(imgs=imgs, ref=ref, mask=mask, show=show, box=(y, x, size))


def signed_error(img, ref, mask, sigma=2.0):
    """Signed luminance error against the reference in the medium, lightly blurred within it (sigma 2, so a blotch
    reads as a patch rather than as pixels); nan where the blurred medium covers under half a pixel -- outside it, but
    not in its pin holes (the night street's fog)."""
    w = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), sigma)
    e = cv2.GaussianBlur((((img - ref) @ mc.Y_RGB) * mask).astype(np.float32), (0, 0), sigma) / np.maximum(w, 1e-6)
    return np.where(w >= 0.5, e, np.nan)


def error_limit(plain_maps):
    """One symmetric colour limit for a setup's maps: the median over the denoisers of the plain maps' 99th percentile
    of |error|, so one denoiser's brightness offset (Ray Reconstruction's) does not set everyone's scale."""
    return max(float(np.median([np.nanpercentile(np.abs(e), 99) for e in plain_maps])), 1e-12)


def error_crops(p):
    """Each denoiser's (plain, + 5 mutations) error maps in the box, and the setup's colour limit."""
    y, x, s = p.box
    maps = {d: tuple(signed_error(img, p.ref, p.mask)[y:y + s, x:x + s] for img in p.imgs[d]) for d in DENOISERS}
    return maps, error_limit([maps[d][0] for d in DENOISERS])


def _header(axes):
    """Over the top row: each denoiser's name centred on its before/after pair, then 'plain' / '+ 5 mutations'."""
    def note(ax, text, x, dy, color=INK, **kw):
        ax.annotate(text, xy=(x, 1.0), xycoords="axes fraction", xytext=(0, dy), textcoords="offset points",
                    ha="center", va="bottom", fontsize=6, color=color, annotation_clip=False, **kw)
    for i, d in enumerate(DENOISERS):
        note(axes[2 * i], NAMES[d], 1.0, 18, fontweight="bold")  # the pair's centre: the right edge of its left panel
        note(axes[2 * i], "plain", 0.5, 10, color=MUTED)
        note(axes[2 * i + 1], "+ 5 mutations", 0.5, 10, color=MUTED)
    note(axes[-1], "reference", 0.5, 18, fontweight="bold")


def _row(axes, root, results, label, hist, titles):
    p = panel(root, results, label, hist)
    imgs, ref, show, (y, x, s) = p.imgs, p.ref, p.show, p.box
    c = results[label]["histories"][hist]
    cells = []
    for d in DENOISERS:
        cells.append((imgs[d][0], "%.4f" % c["m0"][d]["mean"]))
        change = ("%+.0f%%" % (-100 * cut(results, label, hist, d))).replace("-", "−")
        cells.append((imgs[d][1], "%.4f (%s)" % (c["m5"][d]["mean"], change)))
    cells.append((ref, ""))
    for ax, (img, title) in zip(axes, cells):
        ax.imshow(show(img[y:y + s, x:x + s]), interpolation="nearest")
        ax.set_xticks([])
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_edgecolor(GRID)
        ax.set_title(title, fontsize=6, color=INK, pad=2)
    if titles:
        _header(axes)
    axes[0].set_ylabel(textwrap.fill(paper_tables.SETUP_NAMES.get(label, label), 14), fontsize=6, color=INK)


def strip(root, results, labels, out, hist="c200"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(len(labels), 11, figsize=(7.1, 0.82 * len(labels) + 0.35), squeeze=False,
                             gridspec_kw={"wspace": 0.03, "hspace": 0.32})
    for i, label in enumerate(labels):
        _row(axes[i], root, results, label, hist, titles=(i == 0))
    fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def block_titles(results, label, hist="c200"):
    """A setup's block, titles only: row 0 plain, row 1 + 5 mutations; columns DENOISERS, then the reference (named
    in the header)."""
    c = results[label]["histories"][hist]
    plain = ["%.4f" % c["m0"][d]["mean"] for d in DENOISERS]
    mutated = ["%.4f (%s)" % (c["m5"][d]["mean"], ("%+.0f%%" % (-100 * cut(results, label, hist, d))).replace("-", "−"))
               for d in DENOISERS]
    return [plain + [""], mutated + [""]]


# The page and the teaser, laid out in inches from the top left of a figure exactly the paper's text width (7 in) wide:
# it is placed at scale 1, so its fonts print at their sizes.
WIDTH, LABEL, CROP, GAP = 7.0, 0.36, 1.28, 0.05  # the figure, the row labels' column, the teaser's crop, between crops
ROWS = ("plain", "+ 5 mutations", "error\nplain", "error\n+ 5 mutations")  # two lines: a 1.06 in crop's height
PAGE_ROWS = [(0, True), (1, True), (2, False), (3, False)]  # (row, relMSE above its crops)
TEASER_ROWS = [(2, True), (3, True)]
PAGE_BAND = 2.65  # the page's whole frame is this tall: 4.7 in wide at 16:9


def _axes(fig, x, y, w, h):
    """An axes at (x, y) inches from the figure's top left, w x h inches."""
    fw, fh = fig.get_size_inches()
    return fig.add_axes([x / fw, 1.0 - (y + h) / fh, w / fw, h / fh])


def _text(fig, x, y, s, **kw):
    """Text at (x, y) inches from the figure's top left."""
    fw, fh = fig.get_size_inches()
    fig.text(x / fw, 1.0 - y / fh, s, color=kw.pop("color", INK), **kw)


def _cell(ax, title, size):
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_edgecolor(GRID)
    ax.set_title(title, fontsize=size, color=INK, pad=2)


def _error_cmap():
    import matplotlib
    cmap = matplotlib.colormaps["RdBu_r"].copy()
    cmap.set_bad(OUTSIDE)
    return cmap


def _whole_frame(fig, p, x, top, height):
    """The reference's whole frame, `height` tall at (x, top), with the box the crops show; returns its width."""
    from matplotlib.patches import Rectangle
    by, bx, s = p.box
    wide = height * p.ref.shape[1] / p.ref.shape[0]
    ax = _axes(fig, x, top, wide, height)
    ax.imshow(p.show(p.ref))
    ax.add_patch(Rectangle((bx - 0.5, by - 0.5), s, s, fill=False, ec=ORANGE, lw=1.8))
    _cell(ax, "", 8)
    _text(fig, x + wide / 2, top - 0.05, "reference, whole frame", fontsize=9, fontweight="bold", ha="center",
          va="bottom")
    return wide


def _ref_crop(ax, p):
    """The reference in the box, framed in the box's colour."""
    y, x, s = p.box
    ax.imshow(p.show(p.ref[y:y + s, x:x + s]), interpolation="nearest")
    _cell(ax, "", 7.5)
    for sp in ax.spines.values():
        sp.set_edgecolor(ORANGE)
        sp.set_linewidth(1.6)


def _scale(fig, lim, x0, top, height):
    """The error maps' colour scale from (x0, top), `height` tall, under 1 in wide: the bar, its ticks and label, the
    grey swatch."""
    import matplotlib
    bar = _axes(fig, x0, top + 0.24, 0.13, height - 0.93)  # room above and below for its end ticks and words
    scale = matplotlib.cm.ScalarMappable(norm=matplotlib.colors.Normalize(-lim, lim), cmap=_error_cmap())
    cb = fig.colorbar(scale, cax=bar, ticks=[-lim, 0.0, lim])
    cb.ax.set_yticklabels(["−%.2g" % lim, "0", "+%.2g" % lim])
    cb.ax.tick_params(labelsize=7.5, colors=INK, length=2)
    cb.outline.set_edgecolor(GRID)
    cb.set_label("luminance error", fontsize=7.5, color=MUTED)
    # Its words start at the bar and run right, over its own block: centred on the bar they reached the maps beside it.
    _text(fig, x0, top + 0.13, "too bright", fontsize=7.5, ha="left", va="bottom")
    _text(fig, x0, top + height - 0.57, "too dark", fontsize=7.5, ha="left", va="top")
    swatch = _axes(fig, x0, top + height - 0.22, 0.13, 0.13)  # its two lines of words end inside the block
    swatch.set_facecolor(OUTSIDE)
    _cell(swatch, "", 7)
    _text(fig, x0 + 0.19, top + height - 0.155, "outside\nthe medium", fontsize=7, color=MUTED, va="center",
          linespacing=1.0)


def _band(fig, p, lim, top, height):
    """The teaser's top, centred over its grid: the whole frame, the box enlarged beside it, and the colour scale."""
    wide = height * p.ref.shape[1] / p.ref.shape[0]
    x = LABEL + max(0.0, (WIDTH - LABEL - (wide + 0.14 + height + 0.35 + 1.15)) / 2)
    _whole_frame(fig, p, x, top, height)
    x_box = x + wide + 0.14
    _ref_crop(_axes(fig, x_box, top, height, height), p)
    _text(fig, x_box + height / 2, top - 0.05, "reference, the box", fontsize=8.5, fontweight="bold", ha="center",
          va="bottom")
    _scale(fig, lim, x_box + height + 0.35, top, height)


def _grid_height(rows, crop):
    h, prev = 0.24, None  # the column names
    for r, titled in rows:
        h += (0.17 if titled else 0.06) + (0.08 if prev is not None and prev < 2 <= r else 0.0) + crop
        prev = r
    return h


def _grid(fig, p, titles, maps, lim, rows, top, crop, ref_column):
    """The denoisers across and `rows` down from `top`: the crops plain and + 5 mutations and each one's error map on
    the setup's one colour scale; titled rows carry the relMSE (and its change) over their crops. With ref_column, a
    sixth column holds the reference beside the plain and mutated crops, and the colour scale beside the errors."""
    y, x, s = p.box
    names = [NAMES[d] for d in DENOISERS] + (["reference"] if ref_column else [])
    for j, name in enumerate(names):
        _text(fig, LABEL + j * (crop + GAP) + crop / 2, top + 0.2, name, fontsize=8.5, fontweight="bold",
              ha="center", va="bottom")
    x_ref = LABEL + len(DENOISERS) * (crop + GAP)
    yy, prev, errors_top = top + 0.24, None, None
    for r, titled in rows:
        yy += (0.17 if titled else 0.06) + (0.08 if prev is not None and prev < 2 <= r else 0.0)
        for j, d in enumerate(DENOISERS):
            ax = _axes(fig, LABEL + j * (crop + GAP), yy, crop, crop)
            if r < 2:
                ax.imshow(p.show(p.imgs[d][r][y:y + s, x:x + s]), interpolation="nearest")
            else:
                ax.imshow(np.ma.masked_invalid(maps[d][r - 2]), cmap=_error_cmap(), vmin=-lim, vmax=lim,
                          interpolation="nearest")
            _cell(ax, titles[r % 2][j] if titled else "", 7.5)
        if ref_column and r < 2:
            _ref_crop(_axes(fig, x_ref, yy, crop, crop), p)
        if r >= 2 and errors_top is None:
            errors_top = yy
        _text(fig, LABEL / 2, yy + crop / 2, ROWS[r], fontsize=8, rotation=90, ha="center", va="center")
        yy += crop
        prev = r
    if ref_column and errors_top is not None:
        _scale(fig, lim, x_ref + 0.06, errors_top, yy - errors_top)


def page_layout(ref_shape):
    """Where a setup's page puts things, in inches from its top left: the whole frame (x, y, w, h) centred over the
    grid, the crop, the grid's top and columns (the five denoisers, then the reference beside the plain and mutated
    crops) and the page's height, under 1.165 widths so a two-line caption fits the 8.66 in text block."""
    crop = (WIDTH - LABEL - len(DENOISERS) * GAP - 0.03) / (len(DENOISERS) + 1)  # the reference's border inside
    band = PAGE_BAND
    wide = band * ref_shape[1] / ref_shape[0]
    if wide > WIDTH - LABEL:
        wide, band = WIDTH - LABEL, (WIDTH - LABEL) * ref_shape[0] / ref_shape[1]
    top = 0.24 + band + 0.16
    return {"frame": (LABEL + (WIDTH - LABEL - wide) / 2, 0.24, wide, band), "crop": crop, "grid_top": top,
            "columns": list(DENOISERS) + ["reference"], "height": top + _grid_height(PAGE_ROWS, crop) + 0.03}


def page_canvas(p, titles):
    """One setup on a page (its caption names it): the reference's whole frame with the box across the top, then the
    five denoisers and the reference across and four rows down -- the box plain and with + 5 mutations, each row ending
    in the reference, then each one's signed error against the reference on one colour scale, the scale beside them."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    lay = page_layout(p.ref.shape)
    maps, lim = error_crops(p)
    fig = plt.figure(figsize=(WIDTH, lay["height"]))
    x, y, _, h = lay["frame"]
    _whole_frame(fig, p, x, y, h)
    _grid(fig, p, titles, maps, lim, PAGE_ROWS, lay["grid_top"], lay["crop"], ref_column=True)
    return fig


def page_figure(p, titles, out):
    import matplotlib.pyplot as plt
    fig = page_canvas(p, titles)
    fig.savefig(out, dpi=300, facecolor="white")
    plt.close(fig)


def teaser_figure(p, titles, out):
    """The teaser: the whole frame, the box enlarged and the colour scale across the top, then each denoiser's error
    map without and with five mutations, the relMSE over each."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    maps, lim = error_crops(p)
    band = 1.5
    top = 0.24 + band + 0.16
    fig = plt.figure(figsize=(WIDTH, top + _grid_height(TEASER_ROWS, CROP) + 0.03))
    _band(fig, p, lim, 0.24, band)
    _grid(fig, p, titles, maps, lim, TEASER_ROWS, top, CROP, ref_column=False)
    fig.savefig(out, dpi=300, facecolor="white")
    plt.close(fig)


# The cover (the paper's first figure and the project page's, user-chosen 2026-10-24): one setup through one denoiser
# at M cap 200, in columns plain ReSTIR, + 5 mutations and the reference; the whole medium on top with the zoom's box,
# the zoom below. The zoom is the window of RR's frames with the largest drop in shown error where plain and mutated
# are equally bright (within 4%), so it shows reuse's blotches, not Ray Reconstruction's brightness swing.
COVER = ("bunnyswarm_d3", "rr", (80, 336, 200))  # the setup, the denoiser, the zoom (y, x, size)
COVER_GAP = 0.06


def cover_view(mask, pad=12):
    """The square (y, x, side) holding the whole medium and `pad` pixels round it, inside the frame: the cover's
    wide view."""
    ys, xs = np.nonzero(mask)
    h, w = mask.shape
    side = int(min(h, w, max(ys.max() - ys.min(), xs.max() - xs.min()) + 1 + 2 * pad))
    y = int(np.clip((ys.min() + ys.max()) // 2 - side // 2, 0, h - side))
    x = int(np.clip((xs.min() + xs.max()) // 2 - side // 2, 0, w - side))
    return y, x, side


def cover_titles(results, label, den, hist="c200", sep=" · "):
    """The cover's column heads (name, second line): plain ReSTIR and + 5 mutations with the denoiser and the relMSE
    over the whole medium (and its change), then the reference."""
    c = results[label]["histories"][hist]
    change = ("%+.0f%%" % (-100 * cut(results, label, hist, den))).replace("-", "−")
    return [("Plain ReSTIR", "%s%srelMSE %.4f" % (NAMES[den], sep, c["m0"][den]["mean"])),
            ("+ 5 mutations", "%s%srelMSE %.4f (%s)" % (NAMES[den], sep, c["m5"][den]["mean"], change)),
            ("Reference", "path traced")]


def cover_canvas(p, titles, den, zoom, columns=3, width=WIDTH):
    """The cover, `width` inches wide: per column (plain ReSTIR, + 5 mutations, the reference; the first `columns`)
    its head, the whole medium (cover_view) with the box of the zoom (y, x, size), and the zoom framed in the box's
    colour."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    vy, vx, vs = cover_view(p.mask)
    zy, zx, zs = zoom
    if not (vy <= zy and zy + zs <= vy + vs and vx <= zx and zx + zs <= vx + vs):
        raise ValueError("the zoom %s is not inside the whole view %s" % (zoom, (vy, vx, vs)))
    col = (width - (columns - 1) * COVER_GAP) / columns
    top = 0.44 + 0.14 * (max(sub.count("\n") for _, sub in titles[:columns]))  # the heads: a name, then its lines
    fig = plt.figure(figsize=(width, top + 2 * col + COVER_GAP + 0.02))
    imgs = (p.imgs[den][0], p.imgs[den][1], p.ref)
    for j in range(columns):
        x = j * (col + COVER_GAP)
        name, sub = titles[j]
        _text(fig, x + col / 2, 0.21, name, fontsize=10, fontweight="bold", ha="center", va="bottom")
        _text(fig, x + col / 2, top - 0.04, sub, fontsize=8.5, color=MUTED, ha="center", va="bottom",
              linespacing=1.15)
        ax = _axes(fig, x, top, col, col)
        ax.imshow(np.clip(p.show(imgs[j][vy:vy + vs, vx:vx + vs]), 0, 1), interpolation="lanczos")
        ax.add_patch(Rectangle((zx - vx - 0.5, zy - vy - 0.5), zs, zs, fill=False, ec=ORANGE, lw=1.6))
        _cell(ax, "", 8)
        ax = _axes(fig, x, top + col + COVER_GAP, col, col)
        ax.imshow(np.clip(p.show(imgs[j][zy:zy + zs, zx:zx + zs]), 0, 1), interpolation="lanczos")
        _cell(ax, "", 8)
        for sp in ax.spines.values():
            sp.set_edgecolor(ORANGE)
            sp.set_linewidth(1.6)
    return fig


def cover_figure(p, titles, den, zoom, out, **kw):
    import matplotlib.pyplot as plt
    fig = cover_canvas(p, titles, den, zoom, **kw)
    fig.savefig(out, dpi=300, facecolor="white")
    plt.close(fig)


def setup_page(root, results, label, out, hist="c200"):
    page_figure(panel(root, results, label, hist), block_titles(results, label, hist), out)


def history_chart(results, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 2.4), gridspec_kw={"wspace": 0.28})
    labels = [l for l in results if complete(results, l) and complete(results, l, "ship")]
    for i, d in enumerate(DENOISERS):
        for hist, colour, dx in (("ship", BLUE, -0.12), ("c200", ORANGE, 0.12)):
            r = [results[l]["histories"][hist]["m5"][d]["mean"] / results[l]["histories"][hist]["m0"][d]["mean"]
                 for l in labels]
            a.scatter(np.full(len(r), i + dx), r, s=22, color=colour, edgecolors="white", linewidths=0.8, zorder=3,
                      label=("shipped cap" if hist == "ship" else "M cap 200") if i == 0 else None)
            a.plot([i + dx - 0.09, i + dx + 0.09], [np.median(r)] * 2, color=INK, lw=1.2, zorder=4)
        r = [results[l]["histories"]["c200"]["m5"][d]["mean"] / results[l]["histories"]["ship"]["m0"][d]["mean"]
             for l in labels]
        b.scatter(np.full(len(r), i), r, s=22, color=ORANGE, edgecolors="white", linewidths=0.8, zorder=3)
        b.plot([i - 0.09, i + 0.09], [np.median(r)] * 2, color=INK, lw=1.2, zorder=4)
    for ax, ylabel in ((a, "relMSE, 5 mutations / plain"), (b, "M cap 200 + 5 mutations /\nplain at the shipped cap")):
        ax.set_yscale("log")
        ax.axhline(1.0, color=MUTED, lw=0.8, zorder=1)
        ax.set_xticks(range(len(DENOISERS)))
        ax.set_xticklabels([NAMES[d].replace("NRD ", "") for d in DENOISERS], fontsize=7, color=INK)  # fits the width
        ax.set_ylabel(ylabel, fontsize=7, color=INK)
        ax.tick_params(axis="y", labelsize=7, colors=MUTED)
        ax.grid(axis="y", color=GRID, lw=0.5, zorder=0)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    a.legend(fontsize=7, frameon=False, loc="lower left")
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--results")
    a = ap.parse_args(argv)
    with open(a.results or os.path.join(a.root, "five_denoisers", "results.json")) as fh:
        results = json.load(fh)
    figs = os.path.join(a.root, "figs")
    t = teaser_setup(results)
    print("teaser:", t)
    teaser_figure(panel(a.root, results, t), block_titles(results, t), os.path.join(figs, "teaser_five.png"))
    label, den, zoom = COVER
    p = panel(a.root, results, label)
    cover_figure(p, cover_titles(results, label, den), den, zoom, os.path.join(figs, "cover.png"))
    cover_figure(p, cover_titles(results, label, den, sep="\n"), den, zoom, os.path.join(figs, "cover_phone.png"),
                 columns=2, width=3.4)
    strip(a.root, results, STRIP, os.path.join(figs, "five_strip.png"))  # the compact overview
    for label in five_runs.SETUPS:
        setup_page(a.root, results, label, os.path.join(figs, "five_page_%s.png" % label))
    history_chart(results, os.path.join(figs, "history_chart.pdf"))


if __name__ == "__main__":
    main()
