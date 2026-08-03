# Temporal instability across consecutive frames under camera motion.
#
# Raw frame-to-frame difference confounds flicker with legitimate change (the camera moved, so the
# image SHOULD change). Report both, plus the ratio to a raw-ReSTIR run of the same path when
# available, so a configuration that merely moves less is not scored as more stable.
import os
import sys
import glob

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2
import numpy as np


def frames(d):
    fs = sorted(glob.glob(os.path.join(d, "fl.*.png")) + glob.glob(os.path.join(d, "fl.*.exr")))
    out = []
    for f in fs:
        a = cv2.imread(f, cv2.IMREAD_UNCHANGED)
        if a is None:
            continue
        a = np.nan_to_num(a.astype(np.float32), posinf=0, neginf=0)[..., :3]
        if a.max() > 1.5:
            a = a / 255.0
        out.append(a)
    return out


def stats(d):
    f = frames(d)
    if len(f) < 3:
        return None
    g = [x.mean(axis=2) for x in f]
    # Second difference isolates FLICKER from smooth motion: a steadily moving image has a large
    # first difference but a small second one, while per-frame sparkle has a large second difference.
    d1 = [np.abs(g[i] - g[i - 1]) for i in range(1, len(g))]
    d2 = [np.abs(g[i] - 2 * g[i - 1] + g[i - 2]) for i in range(2, len(g))]
    mu = float(np.mean([x.mean() for x in g])) + 1e-9
    return (len(f), float(np.mean([x.mean() for x in d1])) / mu,
            float(np.mean([x.mean() for x in d2])) / mu)


T = os.environ["TEMP"]
labels = sys.argv[1:] or ["flick_base"]
print("Temporal stability under camera motion (lower = steadier)")
print("  d1 = frame-to-frame change, includes legitimate motion")
print("  d2 = SECOND difference -> isolates flicker from smooth motion\n")
print("%-34s %7s %10s %10s" % ("config", "frames", "d1", "d2 (flicker)"))
base = None
for lab in labels:
    s = stats(os.path.join(T, lab))
    if s is None:
        print("%-34s   (no frames)" % lab)
        continue
    n, a, b = s
    tag = ""
    if base is None:
        base = b
    elif base > 0:
        tag = "   %+.1f%%" % (100 * (b / base - 1))
    print("%-34s %7d %10.5f %10.5f%s" % (lab, n, a, b, tag))
