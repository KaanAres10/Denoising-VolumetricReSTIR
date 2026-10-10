"""Where the swarm's blotches live (spec V-C7). A pixel's estimate is (f/p_hat)(X) times the reservoir's normalization
c_hat = runningSum / M, which Eq. 16 keeps: no mutation can change it. FinalShading writes c_hat into the sampleIdentity
output's .z in place of the light id (a diagnostic build of the runtime shader copy only: run_chatz.sh). Per kept frame, the luminance Y splits as log Y = log c_hat + log (Y / c_hat); band-passed to
the blotch scale (2-24 px) inside the medium, each part's share of the blotch variance and its correlation with Y's.

    python chat_maps.py <outputs/decorr>          (prints the table; writes figs/swarm_chat_maps.png)
"""
import glob
import json
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

LABEL = "bunnyswarm_d3"
CONFIGS = (("chatz_c200_m0", "plain ReSTIR"), ("chatz_c200_m10", "10 mutations"), ("chatz_dec200_m0", "decoupled history"))
LUM = np.array([0.0722, 0.7152, 0.2126])  # BGR


def band(x, lo, hi):
    """x blurred at lo px minus x blurred at hi px: the blotch scale."""
    a = cv2.GaussianBlur(x, (0, 0), lo) if lo > 0 else x
    return a - cv2.GaussianBlur(x, (0, 0), hi) if hi < 1e8 else a


def split(y, c, mask, lo=2.0, hi=24.0, ref=None):
    """Blotch variance of log Y and the shares of log c_hat and log (Y / c_hat) (their covariance split evenly). With
    `ref` (the reference's luminance) both are divided by it first, so only the ERROR is split: the scene's own
    structure is in Y and in c_hat alike and would otherwise dominate."""
    if ref is not None:
        good = ref > 0
        y = np.where(good, y / np.where(good, ref, 1), 0.0)
        c = np.where(good, c / np.where(good, ref, 1), 0.0)
        mask = mask & good
    ok = mask & (y > 0) & (c > 0)
    ly = np.where(ok, np.log(np.where(ok, y, 1)), 0.0)
    lc = np.where(ok, np.log(np.where(ok, c, 1)), 0.0)
    # fill the masked-out pixels with the in-mask mean so the blur does not drag the edges
    for a in (ly, lc):
        a[~ok] = a[ok].mean()
    by, bc = band(ly, lo, hi)[ok], band(lc, lo, hi)[ok]
    br = by - bc
    vy = by.var()
    share_c = (bc.var() + np.cov(bc, br)[0, 1]) / vy
    return {"var_y": float(vy), "share_c": float(share_c), "share_r": float(1 - share_c),
            "corr_c": float(np.corrcoef(by, bc)[0, 1]), "corr_r": float(np.corrcoef(by, br)[0, 1])}


def frames(run_dir):
    with open(os.path.join(run_dir, "c.schedule.json")) as fh:
        s = json.load(fh)
    out = []
    for ch in s["chains"]:
        f = ch["frames"][0]
        col = os.path.join(run_dir, "c.VolumetricReSTIR.accumulated_color.%d.exr" % f)
        idn = os.path.join(run_dir, "c.VolumetricReSTIR.sampleIdentity.%d.exr" % f)
        if os.path.exists(col) and os.path.exists(idn):
            img = cv2.imread(col, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float64)
            chat = cv2.imread(idn, cv2.IMREAD_UNCHANGED)[..., 0].astype(np.float64)  # .z (BGR order)
            out.append((img, chat))
    return out


def main(root):
    med = np.load(os.path.join(root, LABEL, "noreuse", "c.medium.npy"))
    ref = cv2.imread(os.path.join(root, LABEL, "ref", "c.Accum.output.2047.exr"), cv2.IMREAD_UNCHANGED)[..., :3]
    ref_y = cv2.GaussianBlur(ref.astype(np.float64) @ LUM, (0, 0), 1.0)  # its per-pixel noise (~5%) slightly smoothed
    rows, maps = [], []
    for cfg, name in CONFIGS:
        d = os.path.join(root, LABEL, cfg)
        if not os.path.exists(os.path.join(d, "c.corr.json")):
            continue
        fs = frames(d)
        ss = [split(img @ LUM, c, med, ref=ref_y) for img, c in fs]
        m = {k: float(np.mean([s[k] for s in ss])) for k in ss[0]}
        rows.append((name, m))
        img, c = fs[0]
        maps.append((name, img, c))
    print("%-20s %12s %18s %18s %10s" % ("config", "blotch var", "share in c_hat", "share in sample", "corr(Y,c)"))
    for name, m in rows:
        print("%-20s %12.4f %17.0f%% %17.0f%% %10.2f" % (name, m["var_y"], 100 * m["share_c"], 100 * m["share_r"], m["corr_c"]))
    if maps:
        figure(root, maps, ref_y, med)


def figure(root, maps, ref_y, med):
    """Per config: the frame, its brightness error log(Y / ref) and the part of it in c_hat, log(c_hat / ref), on one
    diverging scale (blue too dark, red too bright), lightly blurred; the sample's part is what is left."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    y0, y1, x0, x1 = 120, 330, 300, 680  # the cloud's lit core at 960x540
    k = np.percentile(maps[0][1][y0:y1, x0:x1], 99.5)
    fig, axes = plt.subplots(3, len(maps), figsize=(4.6 * len(maps), 7.6), facecolor="#fcfcfb", squeeze=False)
    rows = ("the frame (raw)", "its brightness error, log(Y / reference)", "the part in c_hat, log(c_hat / reference)")
    for c_, (name, img, chat) in enumerate(maps):
        y = img @ LUM
        # blur first, then the log ratio: the log of a sparse noisy pixel is far below the log of its mean, which would
        # paint noisy regions blue though their means agree (checked: the left region's mean matches the reference)
        g = lambda a: cv2.GaussianBlur(np.where(med, a, 0.0), (0, 0), 3) / np.maximum(cv2.GaussianBlur(med.astype(float), (0, 0), 3), 1e-3)  # noqa: E731
        gr = g(ref_y)
        ok = med & (gr > 0)
        ey = np.where(ok, np.log(np.maximum(g(y), 1e-9) / np.where(ok, gr, 1)), np.nan)
        ec = np.where(ok, np.log(np.maximum(g(chat), 1e-9) / np.where(ok, gr, 1)), np.nan)
        tiles = [np.clip(img[y0:y1, x0:x1, ::-1] / k, 0, 1) ** (1 / 2.2), ey[y0:y1, x0:x1], ec[y0:y1, x0:x1]]
        for r_, t in enumerate(tiles):
            ax = axes[r_][c_]
            ax.set_xticks([]); ax.set_yticks([])
            if r_ == 0:
                ax.imshow(t, interpolation="nearest")
                ax.set_title(name, fontsize=12)
            else:
                ax.imshow(t, cmap="RdBu_r", vmin=-0.8, vmax=0.8, interpolation="nearest")
            if c_ == 0:
                ax.set_ylabel(rows[r_], fontsize=9, color="#52514e")
    fig.tight_layout()
    os.makedirs(os.path.join(root, "figs"), exist_ok=True)
    fig.savefig(os.path.join(root, "figs", "swarm_chat_maps.png"), dpi=110, facecolor="#fcfcfb")
    plt.close(fig)

DENOISED_COLS = (("plain ReSTIR", "chatz_c200_m0", "c200_m0"), ("10 mutations", "chatz_c200_m10", "c200_m10"),
                 ("decoupled history", "chatz_dec200_m0", "dec200_m0"))


def denoised_figure(root):
    """The same three configurations raw, through OptiX and through DLSS Ray Reconstruction, each denoiser's brightness
    error against the reference beneath it (blur, then log ratio, as figure()), and the reference; relMSE in the medium
    (equal_time_table.py's) under each denoised crop."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import artifacts as art
    import equal_time_table as et
    y0, y1, x0, x1 = 120, 330, 300, 680
    med = np.load(os.path.join(root, LABEL, "noreuse", "c.medium.npy"))
    ref = art.reference(root, LABEL)  # RGB
    ref_y = ref @ LUM[::-1]
    g = lambda a: cv2.GaussianBlur(np.where(med, a, 0.0), (0, 0), 1.5) / np.maximum(cv2.GaussianBlur(med.astype(float), (0, 0), 1.5), 1e-3)  # noqa: E731
    gr = g(ref_y)
    ok = med & (gr > 0)
    err = lambda img: np.where(ok, np.log(np.maximum(g(img @ LUM[::-1]), 1e-9) / np.where(ok, gr, 1)), np.nan)  # noqa: E731
    k = np.percentile(ref[y0:y1, x0:x1], 99.5)
    tone_ = lambda img: np.clip(img[y0:y1, x0:x1] / k, 0, 1) ** (1 / 2.2)  # noqa: E731
    rows = [("raw frame", None), ("OptiX", "den_optix"), ("OptiX error", "den_optix"), ("Ray Reconstruction", "den_rr"),
            ("RR error", "den_rr"), ("RR error, mean matched", "den_rr")]
    fig, axes = plt.subplots(len(rows), len(DENOISED_COLS) + 1, figsize=(4.4 * (len(DENOISED_COLS) + 1), 2.6 * len(rows)),
                             facecolor="#fcfcfb", squeeze=False)
    for c_, (name, raw_cfg, tail) in enumerate(DENOISED_COLS + (("reference", None, None),)):
        for r_, (rname, den) in enumerate(rows):
            ax = axes[r_][c_]
            ax.set_xticks([]); ax.set_yticks([])
            if r_ == 0:
                ax.set_title(name, fontsize=12)
            if c_ == 0:
                ax.set_ylabel(rname, fontsize=10, color="#52514e")
            if raw_cfg is None:  # the reference column
                if "error" not in rname:
                    ax.imshow(tone_(ref), interpolation="nearest")
                else:
                    ax.axis("off")
                continue
            if den is None:
                fs = frames(os.path.join(root, LABEL, raw_cfg))
                img = fs[0][0][..., ::-1] if fs else None
                rel = None
            else:
                cfg = "%s_%s" % (den, tail)  # e.g. den_rr_c200_m10, den_optix_dec200_m0
                d = os.path.join(root, LABEL, cfg)
                if not os.path.exists(os.path.join(d, "c.corr.json")):
                    ax.text(0.5, 0.5, "running", ha="center", va="center", transform=ax.transAxes, color="#52514e")
                    continue
                img = (art.kept_all(d) or [None])[0]
                rel = (et.scores(root, LABEL, ("%s_c200_noreuse" % den, "%s_c200_m0" % den, cfg)) or {}).get(cfg)
            if img is None:
                continue
            ratio = (img @ LUM[::-1])[med].mean() / ref_y[med].mean()  # the frame's mean brightness over the reference's
            if "error" in rname:
                e = err(img / ratio) if "matched" in rname else err(img)  # matched: RR's overall darkening divided out
                ax.imshow(e[y0:y1, x0:x1], cmap="RdBu_r", vmin=-0.8, vmax=0.8, interpolation="nearest")
            else:
                ax.imshow(tone_(img), interpolation="nearest")
                if rel is not None:
                    ax.set_xlabel("relMSE in the medium %.3f · mean %.2fx the reference" % (rel[0], ratio), fontsize=9, color="#52514e")
    fig.tight_layout()
    fig.savefig(os.path.join(root, "figs", "swarm_denoised_maps.png"), dpi=100, facecolor="#fcfcfb")
    plt.close(fig)


if __name__ == "__main__":
    main(sys.argv[1])
    denoised_figure(sys.argv[1])
