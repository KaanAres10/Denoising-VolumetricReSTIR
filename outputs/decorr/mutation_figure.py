"""What the mutations do to the image: one row per configuration, the same frame of the same seeded chain in
each (the configs share schedules and seeds, so a column differs only by the setting), cropped inside the medium.

Columns: the frame | its error against the reference | that error blurred (sigma 4: blotches survive, grain
does not) | sample identity (pixels holding the SAME sample share a colour: the clumps are what reuse shares)
| mean neighbour correlation rho(r) in the medium, every row on one axis.

    python mutation_figure.py outputs/decorr <label> <config> [<config> ...] [--size 300] [--out file.png]
    e.g. python mutation_figure.py outputs/decorr emerald shipped mcap_50 mcap_50_mut1
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
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art
import m_corr as mc

NAMES = {"shipped": "as shipped", "noreuse": "no reuse"}


def name(cfg):
    if cfg in NAMES:
        return NAMES[cfg]
    parts = cfg.split("_")
    out = []
    if parts[0] == "mcap":
        out.append("M cap " + parts[1])
        parts = parts[2:]
    for p in parts:
        if p.startswith("mut"):
            n = p[3:]
            out.append("+ %s mutation%s" % (n, "" if n == "1" else "s"))
        elif p in ("light", "depth", "both"):
            out.append("(%s)" % p)
    return " ".join(out) or cfg


def make(root, label, configs, size=300, out=None):
    ref = art.reference(root, label)
    rows = []
    for cfg in configs:
        d = os.path.join(root, label, cfg)
        color, ident = art.kept(d)
        with open(os.path.join(d, "c.corr.json")) as fh:
            corr = json.load(fh)
        rows.append((cfg, color, ident, corr))
    crop = art.medium_crop(rows[0][2], size)
    surface = label.split("_")[0] in mc.SURFACE_SCENES
    lum = lambda x: x @ mc.Y_RGB
    k = np.percentile(lum((ref if ref is not None else rows[0][1])[crop]), 99) + 1e-9
    errs = [lum(c) - lum(ref) for _, c, _, _ in rows] if ref is not None else None
    es = max(np.percentile(np.abs(e[crop]), 99) for e in errs) if errs else 1
    blurs = [cv2.GaussianBlur(e, (0, 0), 4) for e in errs] if errs else None
    bs = max(np.percentile(np.abs(b[crop]), 99.5) for b in blurs) if blurs else 1

    ncol = 5 if ref is not None else 3
    fig = plt.figure(figsize=(4 * ncol, 4.1 * len(rows) + 0.6))
    gs = fig.add_gridspec(len(rows), ncol)
    curve = fig.add_subplot(gs[:, ncol - 1])
    for i, (cfg, color, ident, corr) in enumerate(rows):
        block = corr.get("medium") or corr["robust"]
        rho = block["rho"]
        ref_err = corr.get("reference", {})
        a = fig.add_subplot(gs[i, 0]); a.imshow(art.tonemap(color[crop], k)); a.axis("off")
        a.set_title("%s\nsmoke rho(8) %.4f, relMSE %s" % (name(cfg), rho["8"],
                    ("%.5f" % ref_err["relmse"]) if ref_err else "-"), fontsize=10)
        c = 1
        if errs is not None:
            a = fig.add_subplot(gs[i, 1]); a.imshow(errs[i][crop], cmap="RdBu_r", vmin=-es, vmax=es); a.axis("off")
            a.set_title("error vs reference", fontsize=10)
            a = fig.add_subplot(gs[i, 2]); a.imshow(blurs[i][crop], cmap="RdBu_r", vmin=-bs, vmax=bs); a.axis("off")
            level = float(lum(ref[crop]).mean())
            a.set_title("error blurred (sigma 4)\nrms %.1f%% of the mean"
                        % (100 * float(np.sqrt(np.mean(blurs[i][crop] ** 2))) / level), fontsize=10)
            c = 3
        sample, light, at_surface = mc.decode_identity(ident)
        ids = mc.duplicate_ids(sample, light, at_surface, surface)
        # A 64x64 zoom: at the full crop size one colour per sample is too fine to show the clumps.
        y0, x0 = crop[0].start + (size - 64) // 2, crop[1].start + (size - 64) // 2
        zoom = np.s_[y0:y0 + 64, x0:x0 + 64]
        a = fig.add_subplot(gs[i, c]); a.imshow(art.id_colors(ids)[zoom], interpolation="nearest"); a.axis("off")
        a.set_title("sample identity, 64x64 zoom: %.0f of 400 px\nper tile share a sample (same colour)"
                    % mc.duplicate_map(ids[crop]).mean(), fontsize=10)
        radii = sorted(int(r) for r in rho)
        curve.plot(radii, [rho[str(r)] for r in radii], "o-", label=name(cfg))
    curve.set_xscale("log", base=2)
    curve.set_xlabel("box radius r (px)")
    curve.set_ylabel("mean neighbour correlation rho(r), smoke")
    curve.axhline(0, color="k", lw=0.5)
    curve.legend(fontsize=9)
    curve.set_title("correlation vs distance")
    fig.suptitle("%s: what one mutation does (crop %dx%d inside the medium, the same frame and seed per row)"
                 % (label, size, size), fontsize=13)
    fig.tight_layout()
    out = out or os.path.join(root, "mutation_%s.png" % label)
    fig.savefig(out, dpi=70)
    plt.close(fig)
    return out


def frames(root, label, configs, size=220, out=None):
    """The frames alone, large, after the reference: what a viewer sees."""
    ref = art.reference(root, label)
    shots = [("path-traced reference", ref)] if ref is not None else []
    first_ident = None
    for cfg in configs:
        color, ident = art.kept(os.path.join(root, label, cfg))
        first_ident = ident if first_ident is None else first_ident
        with open(os.path.join(root, label, cfg, "c.corr.json")) as fh:
            corr = json.load(fh)
        rho = (corr.get("medium") or corr["robust"])["rho"]["8"]
        shots.append(("%s\nsmoke rho(8) %.4f" % (name(cfg), rho), color))
    crop = art.medium_crop(first_ident, size)
    k = np.percentile((shots[0][1][crop]) @ mc.Y_RGB, 99) + 1e-9
    fig, ax = plt.subplots(1, len(shots), figsize=(5.2 * len(shots), 5.6))
    for a, (title, img) in zip(np.atleast_1d(ax), shots):
        a.imshow(art.tonemap(img[crop], k), interpolation="nearest")
        a.set_title(title, fontsize=12)
        a.axis("off")
    fig.suptitle("%s: one frame each, same seed (crop %dx%d)" % (label, size, size), fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    out = out or os.path.join(root, "mutation_frames_%s.png" % label)
    fig.savefig(out, dpi=80)
    plt.close(fig)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("label")
    ap.add_argument("configs", nargs="+")
    ap.add_argument("--size", type=int, default=300)
    ap.add_argument("--frames", action="store_true", help="the frames alone, large")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.frames:
        print(frames(a.root, a.label, a.configs, a.size, a.out))
    else:
        print(make(a.root, a.label, a.configs, a.size, a.out))
