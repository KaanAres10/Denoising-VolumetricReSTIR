# THE CONTROL: the estimator's undenoised HDR output from both builds, same orbit, same 300 frames.
# No denoiser, no tonemapper, no TAA in either path -- so any difference here is the ESTIMATOR.
#
# Instability is normalised by mean brightness, so the two builds' different exposure handling
# cancels. EXRs are read via OpenCV (BGR; we take luminance, so channel order does not matter).
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
    mu = float(np.mean([x.mean() for x in g])); out = []
    for s in (32, 128):
        b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
        out.append(1e3 * float(np.mean([np.abs(b[i]-2*b[i-1]+b[i-2]).mean() for i in range(2, len(b))])) / mu)
    # Per-pixel noise level: mean absolute frame-to-frame difference, also normalised.
    px = 1e3 * float(np.mean([np.abs(g[i]-g[i-1]).mean() for i in range(1, len(g))])) / mu
    print("%-34s %9.2f %9.2f %11.2f %11.5f" % (label, out[0], out[1], px, mu))

print("%-34s %9s %9s %11s %11s" % ("UNDENOISED estimator output", "s=32", "s=128", "per-pixel", "mean"))
row("LEGACY (Falcor 4.x)", load("../legacy/outputs/Bistro_Raw_Video/*.exr", r"_(\d{4})\.Volumetric"))
row("v8 (current)",        load("orbit_raw_v8/*.exr",                      r"\.(\d+)\.exr"))
