"""What ReSTIR's reuse does to a volumetric image, shown rather than scored: one figure per scene from the
study's kept captures (outputs/decorr/<label>/{noreuse,shipped}) and its reference.

Rows (a crop inside the medium, the same crop throughout):
  1. reference | no reuse | ReSTIR as shipped                              (same exposure)
  2. error vs reference, no reuse | shipped; the same blurred (sigma 4)    blotches survive the blur
  3. sample identity, no reuse | shipped: every distinct reservoir sample a random colour, so pixels
     holding the SAME sample (shared by spatial/temporal reuse) show as clumps of one colour;
     emitter (light-ID) sharing for surface-lit scenes

    python artifacts.py outputs/decorr <label> [--ref path.exr] [--out artifacts_<label>.png]
"""
import argparse
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_corr as mc

BISTRO_REF = "outputs/pending_9p/forkref/cap/v9sa_ref/v9sa_ref.Accum.output.8191.exr"


def kept(run_dir):
    """The run's kept capture (first capture of chain 0): colour (RGB), identity (RGB) or None."""
    with open(os.path.join(run_dir, "c.schedule.json")) as fh:
        s = json.load(fh)
    f = s["chains"][0]["frames"][0]
    color = mc.read_exr(os.path.join(run_dir, "c.%s.%d.exr" % (s.get("channel", "VolumetricReSTIR.accumulated_color"), f)))
    ident = os.path.join(run_dir, "c.VolumetricReSTIR.sampleIdentity.%d.exr" % f)
    ident = mc.read_exr(ident)[..., :3][..., ::-1] if os.path.exists(ident) else None
    return color[..., :3][..., ::-1].astype(np.float64), ident


def reference(root, label, override=None):
    if override:
        return mc.read_exr(override)[..., :3][..., ::-1].astype(np.float64)
    if label == "bistro" and os.path.exists(BISTRO_REF):
        return mc.read_exr(BISTRO_REF)[..., :3][..., ::-1].astype(np.float64)
    refs = sorted(glob.glob(os.path.join(root, label, "ref", "c.Accum.output.*.exr")),
                  key=lambda p: int(p.split(".")[-2]))
    return mc.read_exr(refs[-1])[..., :3][..., ::-1].astype(np.float64) if refs else None


def medium_crop(ident, size):
    """A size x size window centred on the pixels whose sample scattered in the medium."""
    H, W = ident.shape[:2]
    sample, light, at_surface = mc.decode_identity(ident)
    medium = (sample >= 0) & ~at_surface
    ys, xs = np.nonzero(medium)
    if len(ys) == 0:
        cy, cx = H // 2, W // 2
    else:
        cy, cx = int(np.median(ys)), int(np.median(xs))
    s = min(size, H, W)
    y0 = int(np.clip(cy - s // 2, 0, H - s))
    x0 = int(np.clip(cx - s // 2, 0, W - s))
    return np.s_[y0:y0 + s, x0:x0 + s]


def tonemap(x, k):
    t = np.clip(x / k, 0, None)
    return np.clip(t / (1 + t) * 2, 0, 1) ** (1 / 2.2)


def id_colors(ids):
    """Random colour per id, black where there is none (ids < 0)."""
    h = (ids.astype(np.uint64) * np.uint64(2654435761)) & np.uint64(0xFFFFFF)
    rgb = np.stack([(h >> np.uint64(s)) & np.uint64(255) for s in (0, 8, 16)], axis=-1).astype(np.float64) / 255
    rgb = 0.25 + 0.75 * rgb
    rgb[ids < 0] = 0
    return rgb


def make(root, label, ref_path=None, out=None, size=360):
    no_c, no_i = kept(os.path.join(root, label, "noreuse"))
    sh_c, sh_i = kept(os.path.join(root, label, "shipped"))
    ref = reference(root, label, ref_path)
    crop = medium_crop(sh_i, size)
    surface_scene = label.split("_g")[0] in mc.SURFACE_SCENES
    lum = lambda x: x @ mc.Y_RGB
    base = ref if ref is not None else sh_c
    k = np.percentile(lum(base[crop]), 99) + 1e-9

    rows = 4 if ref is not None else 3
    fig, ax = plt.subplots(rows, 3, figsize=(13, 4.3 * rows))
    for a in ax.ravel():
        a.axis("off")
    ax[0, 0].imshow(tonemap(base[crop], k)); ax[0, 0].set_title("reference" if ref is not None else "(no reference)")
    ax[0, 1].imshow(tonemap(no_c[crop], k)); ax[0, 1].set_title("no reuse (1 frame)")
    ax[0, 2].imshow(tonemap(sh_c[crop], k)); ax[0, 2].set_title("ReSTIR as shipped (1 frame)")

    r = 1
    if ref is not None:
        scale = np.percentile(np.abs(lum(sh_c[crop]) - lum(ref[crop])), 99) + 1e-9
        for col, (name, img) in enumerate((("no reuse", no_c), ("shipped", sh_c))):
            e = lum(img) - lum(ref)
            ax[r, col].imshow(e[crop], cmap="RdBu_r", vmin=-scale, vmax=scale)
            ax[r, col].set_title("error vs reference: %s" % name)
        eb_no = cv2.GaussianBlur(lum(no_c) - lum(ref), (0, 0), 4)[crop]
        eb_sh = cv2.GaussianBlur(lum(sh_c) - lum(ref), (0, 0), 4)[crop]
        bs = max(np.percentile(np.abs(eb_sh), 99), np.percentile(np.abs(eb_no), 99)) + 1e-9
        ax[r, 2].imshow(np.hstack([eb_no, np.full((eb_no.shape[0], 4), np.nan), eb_sh]), cmap="RdBu_r", vmin=-bs, vmax=bs)
        ax[r, 2].set_title("error blurred (sigma 4): no reuse | shipped")
        r += 1

    for col, (name, ident) in enumerate((("no reuse", no_i), ("shipped", sh_i))):
        sample, light, at_surface = mc.decode_identity(ident)
        ids = mc.duplicate_ids(sample, light, at_surface, surface_scene)
        ax[r, col].imshow(id_colors(ids)[crop])
        d = mc.duplicate_map(ids[crop])
        ax[r, col].set_title("sample identity, %s\n(%.0f of 400 px per 20x20 tile share a sample)" % (name, d.mean()))
    sample, light, at_surface = mc.decode_identity(sh_i)
    lids = mc.light_ids(light, at_surface, surface_scene)
    if (lids >= 0).any():
        ax[r, 2].imshow(id_colors(lids)[crop])
        ax[r, 2].set_title("shipped: emitter triangle per pixel\n(%.0f of 400 px per tile share one)" % mc.duplicate_map(lids[crop]).mean())
    else:
        sh_dup = mc.duplicate_map(mc.duplicate_ids(sample, light, at_surface, surface_scene))
        im = ax[r, 2].imshow(sh_dup, cmap="magma", vmin=0, vmax=400)
        fig.colorbar(im, ax=ax[r, 2], fraction=0.046)
        ax[r, 2].set_title("shipped: shared-sample pixels per 20x20 tile (whole frame)")
    r += 1

    corr = {}
    for cfg in ("noreuse", "shipped"):
        with open(os.path.join(root, label, cfg, "c.corr.json")) as fh:
            corr[cfg] = json.load(fh)
    ac = np.load(os.path.join(root, label, "shipped", "c.autocorr.npy"))
    h = ac.shape[0] // 2
    ac = ac.copy(); ac[h, h] = np.nan
    im = ax[r, 0].imshow(ac, cmap="RdBu_r", vmin=-0.08, vmax=0.08, extent=[-h - .5, h + .5, h + .5, -h - .5])
    ax[r, 0].axis("on"); fig.colorbar(im, ax=ax[r, 0], fraction=0.046)
    ax[r, 0].set_title("shipped: residual correlation vs pixel offset (dx, dy)")
    rad = sorted(int(x) for x in corr["shipped"]["robust"]["rho"])
    a = ax[r, 1]; a.axis("on")
    for cfg in ("noreuse", "shipped"):
        a.plot(rad, [corr[cfg]["robust"]["rho"][str(x)] for x in rad], "o-", label=cfg)
    a.set_xscale("log", base=2); a.set_xlabel("box radius r (px)"); a.set_ylabel("rho(r)"); a.legend(); a.set_title("mean neighbour correlation")
    t = corr["shipped"].get("temporal") or json.load(open(os.path.join(root, label, "burst", "c.corr.json"))).get("temporal")
    a = ax[r, 2]; a.axis("on")
    if t:
        a.plot(t["rho"][:24], "o-", ms=3); a.axhline(0, color="k", lw=.5)
        a.set_xlabel("frame lag"); a.set_ylabel("temporal correlation"); a.set_title("shipped: same pixel across frames")
    fig.suptitle("%s: ReSTIR artifacts in the medium (crop %dx%d)" % (label, size, size))
    fig.tight_layout()
    out = out or os.path.join(root, "artifacts_%s.png" % label)
    fig.savefig(out, dpi=80)
    plt.close(fig)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("label")
    ap.add_argument("--ref")
    ap.add_argument("--out")
    a = ap.parse_args()
    print(make(a.root, a.label, a.ref, a.out))
