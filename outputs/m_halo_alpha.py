# Where the motion error lives, by how much of each pixel the smoke covers.
#
# Stop-and-go recordings (record_look.py, VR_RECORD_STOPS=3, 960x540): mean |arrival - settled| of the
# frame ARRIVING at each stop against the stop's last frame (identical pose), binned by the estimator's
# mediumAlpha at that pose (halo_masks/, from halo_masks.py). The veil RR laid over the ground beside
# the smoke lives in the faint fringe (alpha < ~0.1); a motion-vector choice that fixes it by handing
# too much of the fringe to the ground instead shows up as a jump in the 0.1-0.7 bins (the smoke's
# visible soft edge cut off in motion). "ground" = smoke-free pixels within 24 px of the fringe.
#
# Luminance on a 1.5 px blur, 8-bit LDR (/255). Usage: python m_halo_alpha.py <capture dir> [...]
import glob, os, re, sys
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ARRIVALS, STOP_FRAMES = (74, 299, 524), 150     # see m_halo_band.py for why these indices
LUM = np.array([0.0722, 0.7152, 0.2126], np.float32)   # BGR
BINS = [("ground", None), ("0-.01", (1e-9, 0.01)), (".01-.1", (0.01, 0.1)), (".1-.3", (0.1, 0.3)),
        (".3-.5", (0.3, 0.5)), (".5-.7", (0.5, 0.7)), (".7-.9", (0.7, 0.9)), (".9-1", (0.9, 1.01))]


def masks():
    out = []
    for f in (19, 39, 59):
        a = cv2.imread(os.path.join(HERE, os.environ.get("HALO_MASKS", "halo_masks"), "alpha.VolumetricReSTIR.mediumAlpha.%d.exr" % f), cv2.IMREAD_UNCHANGED)
        a = a[..., 2] if a.ndim == 3 else a
        fringe = (a > 0) & (a < 0.3)
        near = (a == 0) & (cv2.dilate(fringe.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (49, 49))) > 0)
        out.append([near if r is None else ((a >= r[0]) & (a < r[1])) for _, r in BINS])
    return out


def frames(d):
    fs = glob.glob(os.path.join(HERE, d, "*.png"))
    return sorted(fs, key=lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))


def lum(f):
    return cv2.GaussianBlur(cv2.imread(f).astype(np.float32) @ LUM, (0, 0), 1.5)


M = masks()
w = np.array([[m.sum() for m in ms] for ms in M]).sum(0).astype(np.float64)
print("mean |arrival - settled| (/255) by smoke coverage; 'fringe' = pixel-weighted over 0 < alpha < 0.9")
print("%-18s" % "capture" + "".join("%8s" % n for n, _ in BINS) + "   fringe")
for d in sys.argv[1:]:
    fs = frames(d)
    assert len(fs) == 750, (d, len(fs))
    acc = np.zeros(len(BINS))
    for ms, a in zip(M, ARRIVALS):
        D = np.abs(lum(fs[a]) - lum(fs[a + STOP_FRAMES]))
        acc += np.array([D[m].mean() for m in ms]) / len(ARRIVALS)
    fr = slice(1, 7)
    print("%-18s" % d + "".join("%8.2f" % v for v in acc) + "   %6.2f" % (np.dot(acc[fr], w[fr]) / w[fr].sum()))
