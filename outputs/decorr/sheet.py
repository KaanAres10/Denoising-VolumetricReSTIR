"""A crop sheet for one scene of the decorrelation study: <label dir>/sheet.png.

Per config (every <label>/<config>/c.corr.json): the kept raw frame (tonemapped), the 2D residual
autocorrelation (+-32 px, robust), and the duplicate-sample heatmap when there is one; plus rho(r) raw and
robust for every config on shared axes, with the bootstrap interval.

    python sheet.py outputs/decorr/<label>
"""
import glob
import json
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def _frame(d):
    with open(os.path.join(d, "c.schedule.json")) as fh:
        sched = json.load(fh)
    channel = sched.get("channel", "VolumetricReSTIR.accumulated_color")
    f = sched["chains"][0]["frames"][0]
    path = os.path.join(d, "c.%s.%d.exr" % (channel, f))
    if not os.path.exists(path):
        return None
    x = cv2.imread(path, cv2.IMREAD_UNCHANGED)[..., :3][..., ::-1].astype(np.float64)
    lum = x.mean(axis=2)
    k = np.percentile(lum[lum > 0], 99) if np.any(lum > 0) else 1.0
    t = x / (k + 1e-9)
    return np.clip(t / (1 + t) * 2, 0, 1) ** (1 / 2.2)


def make_sheet(label_dir):
    configs = sorted(os.path.dirname(p) for p in glob.glob(os.path.join(label_dir, "*", "c.corr.json")))
    corr = {}
    for d in configs:
        with open(os.path.join(d, "c.corr.json")) as fh:
            corr[os.path.basename(d)] = json.load(fh)
    n = len(configs)
    fig = plt.figure(figsize=(12, 3.2 * n + 3.5))
    gs = fig.add_gridspec(n + 1, 3, height_ratios=[1.1] + [1] * n)
    for col, kind in enumerate(("raw", "robust")):
        ax = fig.add_subplot(gs[0, col])
        for name, c in corr.items():
            radii = sorted(int(r) for r in c[kind]["rho"])
            v = [c[kind]["rho"][str(r)] for r in radii]
            ci = [c[kind].get("ci", {}).get(str(r), [x, x]) for r, x in zip(radii, v)]
            ax.errorbar(radii, v, yerr=[[x - lo for x, (lo, _) in zip(v, ci)], [hi - x for x, (_, hi) in zip(v, ci)]],
                        marker="o", ms=3, capsize=2, label=name)
        ax.set_xscale("log", base=2)
        ax.set_xlabel("box radius r (px)")
        ax.set_ylabel("mean correlation rho(r)")
        ax.set_title("%s: %s" % (os.path.basename(label_dir), kind))
        ax.axhline(0, color="k", lw=0.5)
        ax.legend(fontsize=7)
    for row, d in enumerate(configs, start=1):
        name = os.path.basename(d)
        img = _frame(d)
        ax = fig.add_subplot(gs[row, 0])
        if img is not None:
            ax.imshow(img)
        ax.set_title("%s (K=%s)" % (name, corr[name].get("K")), fontsize=9)
        ax.axis("off")
        ax = fig.add_subplot(gs[row, 1])
        ac_path = os.path.join(d, "c.autocorr.npy")
        if os.path.exists(ac_path):
            ac = np.load(ac_path)
            h = ac.shape[0] // 2
            ac = ac.copy()
            ac[h, h] = np.nan  # the centre is 1 by definition; leave it out of the colour scale
            im = ax.imshow(ac, cmap="RdBu_r", vmin=-0.2, vmax=0.2, extent=[-h - 0.5, h + 0.5, h + 0.5, -h - 0.5])
            fig.colorbar(im, ax=ax, fraction=0.046)
        ax.set_title("residual autocorrelation (dx, dy)", fontsize=9)
        ax = fig.add_subplot(gs[row, 2])
        dup_path = os.path.join(d, "c.dup_sample.npy")
        if os.path.exists(dup_path):
            im = ax.imshow(np.load(dup_path), cmap="magma", vmin=0, vmax=400)  # a 20x20 tile has 400 pixels
            fig.colorbar(im, ax=ax, fraction=0.046)
            ax.set_title("pixels sharing a sample per 20x20 tile", fontsize=9)
        ax.axis("off")
    fig.tight_layout()
    out = os.path.join(label_dir, "sheet.png")
    fig.savefig(out, dpi=90)
    plt.close(fig)
    return out


if __name__ == "__main__":
    print(make_sheet(sys.argv[1]))
