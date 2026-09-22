# Orbit stability/detail for record_look.py captures (960x540), with m_rr2.py's metric so the rows are
# comparable with the README's RR tables: frames resized to 1280x720 grey; instability = mean |second
# temporal difference| of blurred frames / mean brightness (lower = steadier), plume = the central
# 34-66% columns, surfaces = the rest; detail = mean |x - blur(x, 2)| / mean, plumeDet = the same over
# the plume columns. The instability columns reproduce the README's volume-mvec table within 0.03; its
# "detail" column was computed some other way (0.0484 there, 0.0447/0.0387 here) -- compare detail only
# within this script.
#
# Usage: python m_look_orbit.py <capture dir> [...]
import glob, os, re, sys
from concurrent.futures import ThreadPoolExecutor
import cv2, numpy as np

cv2.setNumThreads(0)
HERE = os.path.dirname(os.path.abspath(__file__))


def load(d):
    got = sorted((int(re.search(r"\.(\d+)\.png$", f).group(1)), f) for f in glob.glob(os.path.join(HERE, d, "*.png")))

    def rd(f):
        im = cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2) / 255.0
        return cv2.resize(im, (1280, 720), interpolation=cv2.INTER_AREA)

    with ThreadPoolExecutor(16) as ex:
        return list(ex.map(rd, [f for _, f in got]))


def score(g, mask, s):
    mu = float(np.mean([x[mask].mean() for x in g]))
    b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
    return 1e3 * float(np.mean([np.abs(b[i] - 2 * b[i - 1] + b[i - 2])[mask].mean() for i in range(2, len(b))])) / mu


inner = np.zeros((720, 1280), bool)
inner[int(0.05 * 720):int(0.95 * 720), int(0.34 * 1280):int(0.66 * 1280)] = True
full = np.ones((720, 1280), bool)
print("%-22s %4s %7s %7s %9s %8s %9s %8s" % ("capture", "n", "s=32", "plume", "surfaces", "detail", "plumeDet", "mean"))
for d in sys.argv[1:]:
    g = load(d)
    mu = float(np.mean([x.mean() for x in g]))
    det = float(np.mean([np.abs(x - cv2.GaussianBlur(x, (0, 0), 2)).mean() for x in g])) / mu
    detp = float(np.mean([np.abs(x - cv2.GaussianBlur(x, (0, 0), 2))[inner].mean() for x in g])) / mu
    print("%-22s %4d %7.2f %7.2f %9.2f %8.4f %9.4f %8.4f"
          % (d, len(g), score(g, full, 32), score(g, inner, 16), score(g, ~inner, 16), det, detp, mu), flush=True)
