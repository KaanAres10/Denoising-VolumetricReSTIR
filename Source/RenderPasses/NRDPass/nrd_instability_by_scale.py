# Temporal instability BY SPATIAL SCALE, with the frame ORDER fixed.
#
# scale.py used sorted(glob(...)) on filenames like fl.TAA_LDR.colorOut.40.png ... .129.png. That sorts
# lexicographically, so the sequence runs 100,101,...,129,40,41,...,99 -- and the metric is a SECOND
# temporal difference, which is meaningless on a scrambled order. Sort numerically.
# Prints both so the size of the error is visible rather than asserted.
import glob, os, re, sys
import cv2, numpy as np

SCALES = [0, 8, 32, 128]

def load(d, numeric):
    fs = glob.glob(os.path.join(d, "fl.*.png"))
    fs = sorted(fs, key=lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1))) if numeric else sorted(fs)
    return [cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2) / 255.0
            for f in fs]

print("Temporal instability x1e-3, normalised by mean brightness. sigma 0 = per-pixel sparkle,")
print("sigma 32-128 = whole regions moving together (what people actually see).\n")
print("%-24s %8s" % ("config", "mean") + "".join("%10s" % ("s=%d" % s) for s in SCALES))
for numeric in (True, False):
    print("--- frame order: %s ---" % ("NUMERIC (correct)" if numeric else "LEXICOGRAPHIC (as scale.py had it)"))
    for d in sys.argv[1:]:
        g = load(d, numeric)
        mu = float(np.mean([x.mean() for x in g]))
        cells = []
        for s in SCALES:
            b = g if s == 0 else [cv2.GaussianBlur(x, (0, 0), s) for x in g]
            d2 = float(np.mean([np.abs(b[i] - 2 * b[i-1] + b[i-2]).mean() for i in range(2, len(b))]))
            cells.append("%10.4f" % (1e3 * d2 / mu))
        print("%-24s %8.4f" % (os.path.basename(d), mu) + "".join(cells))
