"""Measures the Falcor teapot-fire shot (vr_graph.load_teapot_fire) against RenderMan rendering the same shot
(Scripts/swatch/rman_teapot_fire.py with hdr=1: scene-linear radiance, the same camera), light by light -- the fire,
the night dome, the soft boxes -- so each light's level and colour can be matched on its own: per region, each
renderer's mean radiance and Falcor's ratio to RenderMan, per channel; inside the flame, its median red and green.

    python match_teapot.py <rman dir> <falcor dir> [<sheet.png>]

<rman dir> holds <part>_lo.png / <part>_hi.png per part (full, fire, dome, rects); <falcor dir> holds
<part>/teapotfire[_b<n>]/ref (run_study.sh refs) for the parts it has, its full frame being their sum. The sheet shows
RenderMan over Falcor, each part through Blender's Standard view (sRGB, clipped), as the target was rendered.
"""
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import preview_shots as ps  # noqa: E402

PARTS = ("full", "fire", "dome", "rects")
# rows, columns of the 512^2 frame
REGIONS = {"backdrop": np.s_[20:120, 20:120], "backdrop_r": np.s_[150:250, 440:500], "floor_ll": np.s_[440:500, 10:70],
           "pot_body": np.s_[200:260, 200:300], "spout": np.s_[150:200, 60:110], "handle": np.s_[180:240, 400:430],
           "stand": np.s_[400:440, 150:350], "inner_lip": np.s_[143:152, 330:345]}


def read_rman(stem):
    """A hdr=1 capture: <stem>_lo.png (linear 0..1, 16 bit) where it holds, else <stem>_hi.png (0..1024)."""
    lo = cv2.imread(stem + "_lo.png", cv2.IMREAD_UNCHANGED)
    if lo is None:
        return None
    hi = cv2.imread(stem + "_hi.png", cv2.IMREAD_UNCHANGED)
    lo = lo[..., :3][..., ::-1].astype(np.float64) / 65535
    hi = hi[..., :3][..., ::-1].astype(np.float64) / 65535 * 1024
    return np.where(lo < 0.98, lo, hi)


def standard_view(img):
    """Blender's Standard view transform: the sRGB curve on the clipped linear value."""
    x = np.clip(img, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * x ** (1 / 2.4) - 0.055)


def flame(rman_fire):
    """The flame's pixels: where RenderMan's fire alone exceeds 2 in red (the backdrop it lights stays under 0.5)."""
    return rman_fire[..., 0] > 2.0


def load(rman_dir, falcor_dir):
    rm = {p: read_rman(os.path.join(rman_dir, p)) for p in PARTS}
    fa = {}
    for p in PARTS[1:]:
        d = os.path.join(falcor_dir, p)
        labels = sorted(n for n in os.listdir(d) if n.startswith("teapotfire")) if os.path.isdir(d) else []
        if labels:
            fa[p] = ps.frame(os.path.join(d, labels[0]))
    if fa and all(v is not None for v in fa.values()):
        fa["full"] = sum(fa.values())
    return rm, fa


def report(rm, fa):
    mask = flame(rm["fire"])
    for p in PARTS:
        if rm.get(p) is None or fa.get(p) is None:
            continue
        print("== %s" % p)
        for name, sl in REGIONS.items():
            a, b = rm[p][sl].reshape(-1, 3).mean(0), fa[p][sl].reshape(-1, 3).mean(0)
            ratio = np.where(a > 1e-4, b / np.maximum(a, 1e-12), np.nan)
            print("  %-10s rman %-26s falcor %-26s ratio %s" % (name, np.array2string(a, precision=4), np.array2string(b, precision=4),
                                                               np.array2string(ratio, precision=2)))
        if p in ("full", "fire") and mask.any():
            print("  flame (%d px): median red rman %.1f falcor %.1f, green rman %.2f falcor %.2f; Falcor's flame px %d" % (
                mask.sum(), np.median(rm[p][mask][:, 0]), np.median(fa[p][mask][:, 0]), np.median(rm[p][mask][:, 1]),
                np.median(fa[p][mask][:, 1]), flame(fa[p]).sum()))


def sheet(rm, fa, path, width=384):
    cols = []
    for p in PARTS:
        if rm.get(p) is None or fa.get(p) is None:
            continue
        tiles = []
        for who, img in (("RenderMan " + p, rm[p]), ("Falcor " + p, fa[p])):
            t = cv2.resize((standard_view(img)[..., ::-1] * 255).astype(np.uint8), (width, width), interpolation=cv2.INTER_AREA)
            cv2.putText(t, who, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
            cv2.putText(t, who, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            tiles.append(t)
        cols.append(np.concatenate(tiles, 0))
    cv2.imwrite(path, np.concatenate(cols, 1))


def main(argv):
    rm, fa = load(argv[1], argv[2])
    report(rm, fa)
    if len(argv) > 3:
        sheet(rm, fa, argv[3])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
