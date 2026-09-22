import glob, os, re, cv2, numpy as np
cv2.setNumThreads(0)
def files(d, legacy=False):
    fs = glob.glob(os.path.join(d, "*.exr"))
    key = (lambda f: int(re.findall(r"(\d+)", os.path.basename(f))[-2])) if legacy \
          else (lambda f: int(re.search(r"\.(\d+)\.exr$", f).group(1)))
    return sorted(fs, key=key)
def mean_of(f):
    return float(cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean())
for label, d, lg in [("v8 RAW (estimator)", "orbit_raw_v8", False),
                     ("v8 DENOISED (OptiX HDR)", "orbit_optixhdr_lm", False),
                     ("legacy DENOISED (OptiX HDR)", "../legacy/outputs/Bistro_OptixHDR_Video", True)]:
    fs = files(d, lg)
    m = np.array([mean_of(f) for f in fs], dtype=np.float64)
    mu = m.mean()
    # Second difference of the frame mean, normalised -- the "global" term in isolation.
    g = 1e3*float(np.abs(m[2:]-2*m[1:-1]+m[:-2]).mean())/mu
    # Also the plain frame-to-frame relative step, which is easier to reason about.
    step = 100.0*float(np.abs(np.diff(m)).mean())/mu
    print("%-30s n=%3d  mean %.5f  global %8.3f  mean |frame-to-frame| %5.2f%%"
          % (label, len(m), mu, g, step), flush=True)
