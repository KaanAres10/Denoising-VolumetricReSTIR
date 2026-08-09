# Look at the captures the way the app shows them.
#
# Bistro is a night exterior lit only by emissive geometry and vr_graph's loader sets exposure 8.0 --
# 2^8 = 256x -- with the comment "without this the frame is 256x too dark". Tonemapping the raw HDR
# without it leaves only the emissive lights visible against black, which is a rendering mistake in
# the viewer, not a dark render.
import os, sys
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2, numpy as np

EV = float(os.environ.get("LOOK_EV", "8.0"))

def tm(a):
    a = np.nan_to_num(a.astype(np.float32), posinf=0, neginf=0)[..., :3] * (2.0 ** EV)
    a = a / (1.0 + a)
    return np.clip(a ** (1 / 2.2) * 255, 0, 255).astype(np.uint8)

tiles = []
for spec in sys.argv[1:]:
    d, fr, buf, label = spec.split("|")
    p = os.path.join(d, "hv.%s.%s.exr" % (buf, fr))
    a = cv2.imread(p, cv2.IMREAD_UNCHANGED)
    if a is None:
        print("MISSING " + p); continue
    v = np.nan_to_num(a.astype(np.float32), posinf=0, neginf=0)[..., :3] * (2.0 ** EV)
    print("%-34s at EV%+.0f: mean %8.3f  median %8.3f  p99 %8.2f  frac>0.5 %5.1f%%"
          % (label, EV, v.mean(), np.median(v), np.percentile(v, 99),
             100.0 * (v.max(axis=2) > 0.5).mean()))
    t = tm(a)
    cv2.putText(t, label, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
    cv2.putText(t, label, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    tiles.append(cv2.resize(t, (640, 360)))
if tiles:
    rows = [np.hstack(tiles[i:i + 2]) for i in range(0, len(tiles), 2)]
    w = max(r.shape[1] for r in rows)
    cv2.imwrite("look.png", np.vstack([np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0))) for r in rows]))
    print("\nwrote look.png")
