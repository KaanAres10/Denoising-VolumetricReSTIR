# The clean comparison: OptiX's HDR output from both builds. No tonemapper, no TAA, no model
# difference (both fall back to HDR single-frame without motion vectors), and the estimator input was
# already verified identical (per-pixel noise 739.07 vs 739.63). Whatever differs here is the pass.
import glob, os, re
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2, numpy as np

def load(pattern, keyre):
    fs = sorted(glob.glob(pattern), key=lambda f: int(re.search(keyre, os.path.basename(f)).group(1)))
    out = []
    for f in fs:
        a = cv2.imread(f, cv2.IMREAD_UNCHANGED)
        a = np.nan_to_num(a.astype(np.float32), posinf=0, neginf=0)[..., :3].mean(axis=2)
        out.append(cv2.resize(a, (1280, 720), interpolation=cv2.INTER_AREA))
    return out

def row(label, g):
    mu = float(np.mean([x.mean() for x in g])); o = []
    for s in (32, 128):
        b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
        o.append(1e3 * float(np.mean([np.abs(b[i]-2*b[i-1]+b[i-2]).mean() for i in range(2, len(b))])) / mu)
    px = 1e3 * float(np.mean([np.abs(g[i]-g[i-1]).mean() for i in range(1, len(g))])) / mu
    sh = float(np.mean([cv2.Laplacian(x/max(mu,1e-9), cv2.CV_32F).var() for x in g]))
    print("%-30s %9.2f %9.2f %11.2f %11.1f %10.5f" % (label, o[0], o[1], px, sh, mu))

print("%-30s %9s %9s %11s %11s %10s" % ("OptiX HDR output", "s=32", "s=128", "per-pixel", "sharpness", "mean"))
row("LEGACY OptiX (HDR out)", load("../legacy/outputs/Bistro_OptixHDR_Video/*.exr", r"_(\d{4})\.DenoiserPass"))
row("v8 OptiX (HDR out)",     load("orbit_optixhdr_v8/*.exr",                      r"\.(\d+)\.exr"))
