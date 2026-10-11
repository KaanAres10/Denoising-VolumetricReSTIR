"""Measures a render against the user's dust reference picture (2026-10-11): background, dust highlight / mid / shadow
colours (display RGB), the mid-tone chroma, the highlight-to-shadow contrast and how much of the frame is dust; and where
the light falls -- the dust's mean brightness over a 3 x 3 grid of its bounding box (relative to its mean: the light's
direction), and the backdrop's brightness at the top of the frame and below the ring (the studio's gradient).

    python match_reference.py <reference.png> <label dir>...      (each frame shown as preview_shots --film shows it)
"""
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import preview_shots as ps  # noqa: E402

Y = np.array([0.2126, 0.7152, 0.0722])


def stats(img):
    """img: display RGB, 0..255. The dust: brighter than the backdrop (the top rows) and warm."""
    bg = img[:60].reshape(-1, 3).mean(0)
    lum = img @ Y
    dust = (lum > (img[:60] @ Y).mean() + 25) & ((img[..., 0] - img[..., 2]) > 15)
    d = img[dust]
    L = d @ Y
    band = lambda lo, hi: d[(L >= np.percentile(L, lo)) & (L <= np.percentile(L, hi))].mean(0)  # noqa: E731
    hi, mid, lo = band(95, 100), band(45, 55), band(0, 10)
    ys, xs = np.nonzero(dust)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    m = lum[dust].mean()
    grid = np.zeros((3, 3))
    for r in range(3):
        for c in range(3):
            sl = np.s_[y0 + (y1 - y0) * r // 3: y0 + (y1 - y0) * (r + 1) // 3, x0 + (x1 - x0) * c // 3: x0 + (x1 - x0) * (c + 1) // 3]
            sel = dust[sl]
            grid[r, c] = lum[sl][sel].mean() / m if sel.any() else 0
    below = lum[min(y1 + 10, img.shape[0] - 1):][~dust[min(y1 + 10, img.shape[0] - 1):]]
    # the shading: the mean brightness gradient inside the dust (blurred 6 px, off the outline) -- its direction is
    # where the light comes from in the picture (0 = right, 90 = up), its strength how hard each billow is shaded
    inner = cv2.erode(dust.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    Lb = cv2.GaussianBlur(lum.astype(np.float32), (0, 0), 6)
    gx, gy = cv2.Sobel(Lb, cv2.CV_32F, 1, 0, ksize=5)[inner].mean(), -cv2.Sobel(Lb, cv2.CV_32F, 0, 1, ksize=5)[inner].mean()
    return {"light": (float(np.degrees(np.arctan2(gy, gx))), float(np.hypot(gx, gy))), "background": bg, "highlight": hi, "mid": mid, "shadow": lo, "chroma": mid[1:] / mid[0],
            "contrast": (hi @ Y) / max(lo @ Y, 1.0), "coverage": dust.mean(), "grid": grid,
            "backdrop": ((img[:60] @ Y).mean(), below.mean() if below.size else np.nan), "aspect": (x1 - x0) / (y1 - y0)}


def line(name, s):
    f = lambda c: "%3.0f %3.0f %3.0f" % tuple(c)  # noqa: E731
    g = s["grid"]
    return ("%-28s bg %s | hi %s  mid %s  shadow %s | chroma 1:%.2f:%.2f  contrast %.1f  dust %2.0f%%\n%28s light grid %s | "
            "backdrop top %.0f below ring %.0f | ring w/h %.2f | light from %.0f deg, shading %.0f") % (
        name[-28:], f(s["background"]), f(s["highlight"]), f(s["mid"]), f(s["shadow"]), s["chroma"][0], s["chroma"][1],
        s["contrast"], 100 * s["coverage"], "", " / ".join(" ".join("%.2f" % v for v in row) for row in g),
        s["backdrop"][0], s["backdrop"][1], s["aspect"], s["light"][0], s["light"][1])


def aligned(img, ref):
    """img cropped (edges replicated) to the reference's aspect with the ring where the reference has it: its bounding
    box spanning the same fraction of the width and starting at the same height, then resized to the reference."""
    def box(a):
        lum = a @ Y
        dust = (lum > (a[:60] @ Y).mean() + 25) & ((a[..., 0] - a[..., 2]) > 15)
        ys, xs = np.nonzero(dust)
        return ys.min() / a.shape[0], ys.max() / a.shape[0], xs.min() / a.shape[1], xs.max() / a.shape[1]
    ry0, ry1, rx0, rx1 = box(ref)
    H, W = img.shape[:2]
    y0, y1, x0, x1 = (v * n for v, n in zip(box(img), (H, H, W, W)))
    wc = (x1 - x0) / (rx1 - rx0)
    hc = wc * ref.shape[0] / ref.shape[1]
    left, top = x0 - rx0 * wc, y0 - ry0 * hc
    pad = int(max(W, H))
    big = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    crop = big[int(top) + pad:int(top + hc) + pad, int(left) + pad:int(left + wc) + pad]
    return cv2.resize(crop, (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_AREA)


def main(argv):
    curve = "aces" if "--aces" in argv else "film"
    argv = [a for a in argv if a != "--aces"]
    ref = cv2.imread(argv[1])[210:1100, 55:1060][..., ::-1].astype(float)  # the picture, without the page's title
    print(line("reference", stats(ref)))
    for d in argv[2:]:
        img = ps.frame(d)
        if img is not None:
            shown = ps.tile(img, "", width=960, filmic=curve == "film", acescurve=curve == "aces")
            print(line(curve + " " + d, stats(aligned(shown[..., ::-1].astype(float), ref))))


if __name__ == "__main__":
    main(sys.argv)
