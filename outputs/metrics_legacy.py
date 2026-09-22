# Temporal instability for the LEGACY OptiX sequence, on the same footing as the v8 numbers:
# downscaled to 1280x720 so sigma=32/128 mean the same fraction of frame, numeric frame order.
import glob, os, re
import cv2, numpy as np

def load(pattern, keyre):
    fs = sorted(glob.glob(pattern), key=lambda f: int(re.search(keyre, os.path.basename(f)).group(1)))
    return [cv2.resize(cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2) / 255.0,
                       (1280, 720), interpolation=cv2.INTER_AREA) for f in fs], len(fs)

def row(label, g):
    mu = float(np.mean([x.mean() for x in g])); out = []
    for s in (32, 128):
        b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
        out.append(1e3 * float(np.mean([np.abs(b[i]-2*b[i-1]+b[i-2]).mean() for i in range(2, len(b))])) / mu)
    m = np.array([x.mean() for x in g])
    gl = 1e3 * float(np.abs(m[2:]-2*m[1:-1]+m[:-2]).mean()) / mu
    sh = float(np.mean([cv2.Laplacian(x*255.0, cv2.CV_32F).var() for x in g]))
    print("%-40s %8.2f %8.2f %12.4f %11.1f %9.4f" % (label, out[0], out[1], gl, sh, mu))

print("%-40s %8s %8s %12s %11s %9s" % ("config", "s=32", "s=128", "whole-frame", "sharpness", "mean"))
g, n = load("../legacy/outputs/Bistro_Optix_Video/*.png", r"_(\d{4})\.ToneMapper")
row("LEGACY OptiX (Falcor 4.x, no TAA)", g)
for tag, lab in (("optix", "v8 OptiX (mvec, +TAA)"), ("optix_nomv", "v8 OptiX (colour only, +TAA)")):
    g, n = load("orbit_%s/*.png" % tag, r"\.(\d+)\.png")
    row(lab, g)
