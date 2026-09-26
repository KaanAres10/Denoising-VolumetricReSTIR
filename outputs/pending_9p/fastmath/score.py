"""m_denoisers.py's temporal-instability metric for one capture folder: score.py <dir> <label>.
Columns as in the locked table: s=32 (low-frequency flicker, whole image), centre and outer regions at
s=16, detail (high-frequency residual). Lower is steadier. Also the mean level, for a brightness check."""
import glob, os, re, sys
import cv2, numpy as np
cv2.setNumThreads(0)
d, label = sys.argv[1], sys.argv[2]
got = []
for f in glob.glob(d + "/*.png"):
    m = re.search(r"\.(\d+)\.png$", os.path.basename(f))
    if m: got.append((int(m.group(1)), f))
if not got:
    print("B %-24s (no frames)" % label); sys.exit()
g = [cv2.resize(cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2) / 255.0,
                (1280, 720), interpolation=cv2.INTER_AREA) for _, f in sorted(got)]
h, w = g[0].shape
inner = np.zeros((h, w), bool); inner[int(0.05 * h):int(0.95 * h), int(0.34 * w):int(0.66 * w)] = True
def sc(mask, s):
    mu = float(np.mean([x[mask].mean() for x in g]))
    b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
    return 1e3 * float(np.mean([np.abs(b[i] - 2 * b[i - 1] + b[i - 2])[mask].mean() for i in range(2, len(b))])) / mu
mu = float(np.mean([x.mean() for x in g]))
det = float(np.mean([np.abs(x - cv2.GaussianBlur(x, (0, 0), 2)).mean() for x in g])) / mu
print("B %-24s n %3d  s=32 %7.2f  centre %8.2f  outer %8.2f  detail %.4f  mean %.4f"
      % (label, len(g), sc(np.ones((h, w), bool), 32), sc(inner, 16), sc(~inner, 16), det, mu), flush=True)
