# Instability by spatial scale + detail retention, for all five denoisers on the 1080p orbit.
#
# Frames are downscaled to 1280x720 before measuring so sigma=32/128 mean the same fraction of the
# frame as in every earlier number in STATE.md -- a sigma in pixels is not comparable across
# resolutions, and silently changing what the metric means is how tables stop being comparable.
#
# Frame order is numeric: filenames are .30.png ... .329.png, so a glob-ordered read runs 100..329
# before 30..99, and this is a SECOND temporal difference, which that scrambling destroys.
import glob, os, re
import cv2, numpy as np

def load(tag):
    d = "orbit_%s" % tag
    fs = sorted(glob.glob(os.path.join(d, "*.png")),
                key=lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))
    out = []
    for f in fs:
        im = cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2) / 255.0
        out.append(cv2.resize(im, (1280, 720), interpolation=cv2.INTER_AREA))
    return out

print("%-8s %8s %8s %12s %11s %9s" % ("config", "s=32", "s=128", "whole-frame", "sharpness", "mean"))
for tag in ("relax", "reblur", "rr", "oidn", "optix"):
    g = load(tag)
    mu = float(np.mean([x.mean() for x in g]))
    cells = []
    for s in (32, 128):
        b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
        d2 = float(np.mean([np.abs(b[i] - 2 * b[i-1] + b[i-2]).mean() for i in range(2, len(b))]))
        cells.append(1e3 * d2 / mu)
    m = np.array([x.mean() for x in g])
    gl = 1e3 * float(np.abs(m[2:] - 2 * m[1:-1] + m[:-2]).mean()) / mu
    sh = float(np.mean([cv2.Laplacian(x * 255.0, cv2.CV_32F).var() for x in g]))
    print("%-8s %8.2f %8.2f %12.4f %11.1f %9.4f" % (tag, cells[0], cells[1], gl, sh, mu))
