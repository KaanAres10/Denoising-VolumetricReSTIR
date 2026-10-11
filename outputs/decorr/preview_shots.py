"""Contact sheet of path-traced previews (run_study.sh refs into a scratch STUDY_OUT), for judging a new shot's look:

    python preview_shots.py [--bright | --film | --aces] <out.png> <label dir>...   (a label dir holds ref/; titled by its last two parts)

Each frame tone-mapped with film_figures.display, exposed at its lit pixels' median brightness, or with --bright at
its 97th percentile (a subject on a dark backdrop: the backdrop's share of the frame then sets nothing); --film as
--bright, but each channel through its own t / (1 + t), so highlights pale as on film (to compare with a filmic
reference render).
"""
import glob
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art  # noqa: E402
import film_figures as ff  # noqa: E402


def frame(d):
    refs = sorted(glob.glob(os.path.join(d, "ref", "c.Accum.output.*.exr")), key=lambda p: int(p.split(".")[-2]))
    return art.reference(None, None, override=refs[-1]) if refs else None


def plane_depth(shape, position, target, focal_mm, plane_y, frame_h_mm=24.0):
    """Each pixel's distance from a pinhole camera (Falcor's: frame height 24 mm, up +y) to the plane y = plane_y
    along its ray; inf where the ray never meets it."""
    H, W = shape
    p, f = np.asarray(position, float), np.asarray(target, float) - np.asarray(position, float)
    f /= np.linalg.norm(f)
    r = np.cross(f, (0.0, 1.0, 0.0))
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    tan = frame_h_mm / 2 / focal_mm
    x = ((2 * (np.arange(W) + 0.5) / W - 1) * tan * W / H)[None, :, None]
    y = ((1 - 2 * (np.arange(H) + 0.5) / H) * tan)[:, None, None]
    d = f[None, None] + x * r[None, None] + y * u[None, None]
    with np.errstate(divide="ignore"):
        t = (plane_y - p[1]) / d[..., 1]
    return np.where(t > 0, t * np.linalg.norm(d, axis=-1), np.inf)


def lens_blur(img, position, target, focal_mm, focus, max_blur, plane_y, frame_h_mm=24.0):
    """A depth-of-field look for display (the renderer's camera is a pinhole): each pixel blurred by a circle of
    confusion growing with its relative distance from the focus, |1 - focus / depth| (depth: plane_depth), reaching
    `max_blur` pixels at 30% off the focus and capped at twice that."""
    depth = plane_depth(img.shape[:2], position, target, focal_mm, plane_y, frame_h_mm)
    coc = max_blur * np.minimum(np.abs(1 - focus / np.minimum(depth, 1e6)) / 0.3, 2.0)
    levels = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0])
    levels = levels[levels <= coc.max() + 1e-6] if coc.max() > 0 else levels[:1]
    stack = [img if s == 0 else cv2.GaussianBlur(img, (0, 0), s / 2) for s in levels]
    i = np.clip(np.searchsorted(levels, coc) - 1, 0, len(levels) - 1)
    j = np.minimum(i + 1, len(levels) - 1)
    w = np.where(j > i, (coc - levels[i]) / np.maximum(levels[j] - levels[i], 1e-6), 0.0)[..., None]
    pick = lambda k: np.choose(k[..., None].repeat(img.shape[2], -1), stack)  # noqa: E731
    return ((1 - w) * pick(i) + w * pick(j)).astype(img.dtype)


def bloom(img, threshold, strength=0.08, radius=8.0):
    """A soft glow around the brightest parts (for display): what exceeds `threshold`, blurred, added back."""
    return img + strength * cv2.GaussianBlur(np.maximum(img - threshold, 0).astype(np.float32), (0, 0), radius)


def film(img, k):
    t = np.clip(img / k, 0, None)
    return (t / (1 + t)) ** (1 / 2.2)


def aces(img, k):
    """Narkowicz's fit of the ACES filmic curve, per channel, then gamma 2.2."""
    x = np.clip(img / k, 0, None)
    return np.clip(x * (2.51 * x + 0.03) / (x * (2.43 * x + 0.59) + 0.14), 0, 1) ** (1 / 2.2)


def tile(img, label, width=640, bright=False, filmic=False, acescurve=False):
    v = img.max(-1)
    lit = v > 1e-3 * np.percentile(v, 99.9)
    if acescurve:
        out = aces(img, np.percentile(v, 97) / 0.7)
    elif filmic:
        out = film(img, np.percentile(v, 97) / 2.6)
    else:
        out = ff.display(img, np.percentile(v, 97) / 2 if bright else ff.exposure(v, lit))
    out = cv2.resize((out[..., ::-1] * 255).astype(np.uint8), (width, int(width * img.shape[0] / img.shape[1])),
                     interpolation=cv2.INTER_AREA)
    cv2.putText(out, label, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
    cv2.putText(out, label, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return out


def main(argv):
    bright, filmic, acescurve = argv[1] == "--bright", argv[1] == "--film", argv[1] == "--aces"
    argv = argv[1:] if bright or filmic or acescurve else argv
    out, dirs = argv[1], argv[2:]
    title = lambda d: "/".join(os.path.normpath(d).replace("\\", "/").split("/")[-2:])  # noqa: E731
    tiles = [tile(f, title(d), bright=bright, filmic=filmic, acescurve=acescurve) for d in dirs for f in [frame(d)] if f is not None]
    if len(tiles) % 2:
        tiles.append(np.zeros_like(tiles[0]))
    cv2.imwrite(out, np.concatenate([np.concatenate(tiles[i:i + 2], 1) for i in range(0, len(tiles), 2)], 0))
    print(out, len(tiles))


if __name__ == "__main__":
    main(sys.argv)
