"""The artifact atlas at a glance: one row per scene, one column per configuration, each cell a crop inside the
medium of one frame (same seed everywhere) above its error against the reference, blurred at sigma 4 so the grain
averages out and the blotches reuse makes remain. A shared colour scale per row; titles give the medium's
neighbour correlation rho(8), the colour correlation and the blurred error.

    python atlas_figure.py outputs/decorr [--out atlas.png] [--scenes a,b,..] [--configs a,b|c,..]

A config "b|c" is the first of b, c that was run for the scene.
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
from mutation_figure import name

SCENES = {"bunnyrgb": "bunny, 3 coloured lights", "bunnyone": "bunny, 1 light (front)",
          "bunnyback_g0.8": "bunny, 1 light behind, g = 0.8", "plumeone": "plume, 1 light",
          "bunnyone_d5": "bunny 5x density, 1 light", "plume_g-0.9": "plume g = -0.9, sky",
          "emerald": "Emerald Square fog", "bistro": "Bistro",
          "bunnyinside": "bunny, lamp inside", "bunnyinside_g0.8": "bunny, lamp inside, g = 0.8",
          "bunnyspot": "bunny, spotlight beam", "bunnyspot_g0.8": "bunny, spotlight beam, g = 0.8",
          "bunnyparty": "bunny, 8 coloured lights", "plumeback_g0.9": "plume backlit, g = 0.9",
          "bunnyslabs": "bunny, light through slats (slabs in depth)",
          "bunnystripes": "bunny, light through slats (stripes)",
          "bunnysoftbox": "bunny, warm + cool panel lights", "bunnylanterns": "bunny, 48 coloured lanterns",
          "bunnyback_g0.95": "bunny, 1 light behind, g = 0.95"}
CONFIGS = ["shipped", "mcap_50", "mcap_50_mut5", "dec_mcap_200"]
BRIGHT_CROP = ("bunnyspot", "bunnyinside")  # crop where the light is, not the medium's centre


def resolve(root, label, spec):
    """The first of spec's "|"-separated configs that was run and scored for this scene, or None."""
    return next((c for c in spec.split("|") if os.path.exists(os.path.join(root, label, c, "c.corr.json"))), None)


def cell(root, label, cfg):
    if cfg is None:
        return None
    d = os.path.join(root, label, cfg)
    color, ident = art.kept(d)
    with open(os.path.join(d, "c.corr.json")) as fh:
        corr = json.load(fh)
    return color, ident, corr


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--out")
    ap.add_argument("--scenes", default=",".join(SCENES))
    ap.add_argument("--configs", default=",".join(CONFIGS))
    ap.add_argument("--size", type=int, default=260)
    ap.add_argument("--colour", action="store_true",
                    help="bottom row: the COLOUR error (chromaticity vs the reference's), blurred, in false colour")
    a = ap.parse_args(argv)
    scenes = [s for s in a.scenes.split(",") if os.path.exists(os.path.join(a.root, s, "shipped", "c.corr.json"))]
    configs = a.configs.split(",")
    ncol = 1 + len(configs)
    fig, ax = plt.subplots(2 * len(scenes), ncol, figsize=(3.3 * ncol, 3.5 * 2 * len(scenes)), squeeze=False)
    for i, label in enumerate(scenes):
        ref = art.reference(a.root, label)
        found = [resolve(a.root, label, spec) for spec in configs]
        cells = [cell(a.root, label, c) for c in found]
        first = next(c for c in cells if c is not None)
        crop = art.medium_crop(first[1], a.size)
        if ref is not None and label.split("_")[0] in BRIGHT_CROP:
            # Mostly unlit scenes (a spotlight's patch, a lamp's pockets): the window with the most light.
            h = a.size // 2
            box = cv2.blur((ref @ mc.Y_RGB).astype(np.float32), (a.size, a.size))
            box[:h, :] = box[-h:, :] = 0
            box[:, :h] = box[:, -h:] = 0
            y, x = np.unravel_index(np.argmax(box), box.shape)
            crop = np.s_[y - h:y + h, x - h:x + h]
        k = np.percentile((ref[crop] if ref is not None else first[0][crop]) @ mc.Y_RGB, 99) + 1e-9
        def chroma(x):
            return x / (x.sum(axis=-1, keepdims=True) + 1e-6)
        blur = lambda x: cv2.GaussianBlur(x.astype(np.float32), (0, 0), 4)
        if a.colour:  # chromaticity of the blurred frame vs the blurred reference's: the colour blotches alone.
            # Blur first: each pixel holds ONE light's colour, and the chromaticities of a red and a green pixel
            # of equal luminance average to the wrong colour; their energies average to the right one.
            blurs = [None if c is None or ref is None else chroma(blur(c[0][crop])) - chroma(blur(ref[crop]))
                     for c in cells]
        else:
            blurs = [None if c is None or ref is None else
                     cv2.GaussianBlur((c[0] - ref)[crop].astype(np.float32) @ mc.Y_RGB.astype(np.float32), (0, 0), 4)
                     for c in cells]
        scale = max((np.percentile(np.abs(b), 99.5) for b in blurs if b is not None), default=1.0)
        level = float((ref[crop] @ mc.Y_RGB).mean()) if ref is not None else 1.0
        top, bot = ax[2 * i], ax[2 * i + 1]
        if ref is not None:
            top[0].imshow(art.tonemap(ref[crop], k))
        top[0].set_title("%s\npath-traced reference" % SCENES.get(label, label), fontsize=10)
        legend = ("colour error vs reference,\nblurred (sigma 4):\ncolour blotches only\n\ngrey = right colour,\n"
                  "tint = the blotch's colour cast") if a.colour else \
                 "error vs reference,\nblurred (sigma 4):\nblotches only\n\nred brighter,\nblue darker"
        bot[0].text(0.5, 0.5, legend, ha="center", va="center", fontsize=10, transform=bot[0].transAxes)
        for j, (cfg, c, b) in enumerate(zip(found, cells, blurs), start=1):
            if c is None:
                top[j].text(0.5, 0.5, "not run", ha="center", va="center", transform=top[j].transAxes)
                continue
            color, _, corr = c
            m = corr.get("medium") or corr["robust"]
            colour = corr.get("color_rb", {}).get("rho", {}).get("8")
            top[j].imshow(art.tonemap(color[crop], k), interpolation="nearest")
            top[j].set_title("%s\nrho(8) %.4f%s" % (name(cfg), m["rho"]["8"],
                             ", colour %.4f" % colour if colour is not None else ""), fontsize=10)
            if b is not None and a.colour:
                bot[j].imshow(np.clip(0.5 + 0.5 * b / scale, 0, 1))
                bot[j].set_title("blurred colour error %.2f%%" % (100 * float(np.sqrt(np.mean(np.sum(b ** 2, axis=-1))))),
                                 fontsize=9)
            elif b is not None:
                bot[j].imshow(b, cmap="RdBu_r", vmin=-scale, vmax=scale)
                bot[j].set_title("blurred error %.1f%% of mean, relMSE %.4f"
                                 % (100 * float(np.sqrt(np.mean(b ** 2))) / level, corr["reference"]["relmse"]),
                                 fontsize=9)
        for x in list(top) + list(bot):
            x.axis("off")
    fig.suptitle("Artifact atlas: one frame per configuration (same seed), crop inside the medium; "
                 "lower is better for every number", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    out = a.out or os.path.join(a.root, "atlas.png")
    fig.savefig(out, dpi=60)
    print(out)


if __name__ == "__main__":
    main()
