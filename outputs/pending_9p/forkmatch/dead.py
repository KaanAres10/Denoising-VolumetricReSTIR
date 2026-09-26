"""Share of raw-estimator pixels with NO contribution (all channels <= 0), plume band (centre third of the
frame, as m_raw300.py) vs surfaces (the rest), every 15th frame of a 300-frame raw EXR orbit.
   dead.py <label> <dir> [legacy]"""
import os; os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import glob, re, sys, cv2, numpy as np
label, d = sys.argv[1:3]; legacy = len(sys.argv) > 3
got = []
for f in glob.glob(d + "/*.exr"):
    m = re.search(r"_(\d{4})\." if legacy else r"\.(\d+)\.exr$", os.path.basename(f))
    if m: got.append((int(m.group(1)), f))
P, S, M = [], [], []
for _, f in sorted(got)[::15]:
    g = cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3]
    h, w = g.shape[:2]
    m = np.zeros((h, w), bool); m[int(0.05 * h):int(0.95 * h), int(0.34 * w):int(0.66 * w)] = True
    z = g.max(-1) <= 0
    P.append(z[m].mean()); S.append(z[~m].mean()); M.append(g.mean())
print("%-28s n=%2d  dead: plume %6.2f%%  surfaces %6.2f%%   frame mean %.6f" % (label, len(P), 100 * np.mean(P), 100 * np.mean(S), np.mean(M)), flush=True)
