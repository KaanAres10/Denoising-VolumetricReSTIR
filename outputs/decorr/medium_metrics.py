"""In-medium image metrics for the paper's runs (docs/superpowers/specs/2026-10-20-mutation-paper-design.md):
paper_figure.prepare's relMSE (the noreuse run's medium mask; luminance clipped at the reference's brightest 0.5%
there), the mean brightness against the reference's, and a reference's own relMSE. Frame, reference and mask must
have one size: a mismatch raises instead of broadcasting.
"""
import glob
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_corr as mc  # noqa: E402


def _check(img, ref, mask):
    if img.shape[:2] != ref.shape[:2] or mask.shape != ref.shape[:2]:
        raise ValueError("sizes differ: frame %s, reference %s, mask %s" % (img.shape[:2], ref.shape[:2], mask.shape))
    if not mask.any():
        raise ValueError("empty medium mask")


def relmse(img, ref, mask):
    _check(img, ref, mask)
    lref = ref @ mc.Y_RGB
    cl = np.percentile(lref[mask], 99.5)
    d = (np.minimum(img @ mc.Y_RGB, cl) - np.minimum(lref, cl))[mask]
    return float(np.mean(d ** 2) / max(np.mean(np.minimum(lref, cl)[mask] ** 2), 1e-20))


def brightness(img, ref, mask):
    _check(img, ref, mask)
    return float((img @ mc.Y_RGB)[mask].mean() / max((ref @ mc.Y_RGB)[mask].mean(), 1e-20))


def accumulations(ref_dir):
    """A reference run's accumulations, fewest frames first (correlation_pose.py writes FRAMES/2 and FRAMES)."""
    paths = sorted(glob.glob(os.path.join(ref_dir, "c.Accum.output.*.exr")), key=lambda p: int(p.split(".")[-2]))
    if len(paths) < 2:
        raise FileNotFoundError("%s holds %d accumulations, not 2" % (ref_dir, len(paths)))
    return [mc.read_exr(p)[..., :3][..., ::-1].astype(np.float64) for p in paths]


def own_relmse(ref_dir, mask):
    """The reference's own error: its half accumulation against its full one (their difference has the full one's
    variance: V-C7's measure)."""
    half, full = accumulations(ref_dir)[-2:]
    return relmse(half, full, mask)
