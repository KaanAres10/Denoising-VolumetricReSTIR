"""Per-pixel flicker of a denoised video (run_apparent.sh): the temporal standard deviation over consecutive frames,
relative to the mean level. A denoiser removes independent noise but keeps reuse's blotches, so what still flickers
after denoising is the blotches crawling. One map per config, shared colour scale.

    python flicker_map.py <root> <label> [--configs restir,mut5,mut16] [--out F]
"""
import argparse
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_corr as mc
from make_video import NAMES, burst_frames
from paper_figure import lit_region


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("label")
    ap.add_argument("--configs", default="restir,mut5,mut16")
    ap.add_argument("--out")
    ap.add_argument("--title", default="")
    a = ap.parse_args(argv)
    cfgs = [c for c in a.configs.split(",") if os.path.isdir(os.path.join(a.root, "video", a.label, c))]
    stds, means = [], []
    for c in cfgs:
        lum = np.stack([f @ mc.Y_RGB for f in burst_frames(os.path.join(a.root, "video", a.label, c))])
        stds.append(lum.std(axis=0))
        means.append(lum.mean(axis=0))
    level = means[0]
    y0, y1, x0, x1 = lit_region(np.repeat(level[..., None], 3, axis=-1))
    lit = level > 0.03 * np.percentile(level, 99)
    rel = [s / (level + 0.05 * level[lit].mean()) for s in stds]
    lim = np.percentile(rel[0][lit], 99)
    fig, ax = plt.subplots(1, len(cfgs), figsize=(6.2 * len(cfgs), 4.6), squeeze=False)
    for j, (c, r) in enumerate(zip(cfgs, rel)):
        im = ax[0][j].imshow(r[y0:y1, x0:x1], cmap="magma", vmin=0, vmax=lim)
        ax[0][j].set_title("%s\nmean flicker in the lit area %.3f" % (NAMES.get(c, c), float(r[lit].mean())), fontsize=12)
        ax[0][j].axis("off")
    fig.colorbar(im, ax=ax[0].tolist(), shrink=0.8, label="temporal std / mean level")
    fig.suptitle(a.title or "Flicker after denoising over %d consecutive frames (bright = boiling blotches)" % len(lum),
                 fontsize=13)
    out = a.out or os.path.join(a.root, "figs", "flicker_%s.png" % a.label)
    fig.savefig(out, dpi=90, bbox_inches="tight")
    print(out, ["%s %.4f" % (c, float(r[lit].mean())) for c, r in zip(cfgs, rel)])


if __name__ == "__main__":
    main()
