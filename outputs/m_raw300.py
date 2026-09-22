import glob, os, re, cv2, numpy as np
cv2.setNumThreads(0)
def files(d, legacy=False):
    got = []
    for f in glob.glob(os.path.join(d, "*.exr")):
        b = os.path.basename(f)
        m = (re.search(r"_(\d{4})\.", b) if legacy else re.search(r"\.(\d+)\.exr$", b))
        if m: got.append((int(m.group(1)), f))
    return [f for _, f in sorted(got)]
def region_stats(label, d, legacy=False, step=15):
    fs = files(d, legacy)[::step]
    if not fs: print("%-26s (no frames)" % label, flush=True); return
    pm, sm, pmean, smean = [], [], [], []
    for f in fs:
        g = cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2)
        h, w = g.shape
        m = np.zeros((h, w), bool); m[int(0.05*h):int(0.95*h), int(0.34*w):int(0.66*w)] = True
        pm.append(float(np.median(g[m])));  pmean.append(float(g[m].mean()))
        sm.append(float(np.median(g[~m]))); smean.append(float(g[~m].mean()))
    print("%-26s n=%2d  plume med %.6f mean %.6f | surf med %.6f mean %.6f"
          % (label, len(fs), np.mean(pm), np.mean(pmean), np.mean(sm), np.mean(smean)), flush=True)
print("RAW estimator output, 300-frame runs, same orbit:", flush=True)
region_stats("legacy RAW (today)", "../legacy/outputs/Bistro_Raw_Today", True)
region_stats("v8 RAW", "orbit_raw_v8", False)
print(flush=True)
print("DENOISED, for reference:", flush=True)
region_stats("legacy denoised", "../legacy/outputs/Bistro_OptixHDR_Video", True)
region_stats("v8 denoised", "orbit_optixhdr_lm", False)
