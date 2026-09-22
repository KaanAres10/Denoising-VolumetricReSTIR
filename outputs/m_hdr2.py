import glob, os, re, cv2, numpy as np
cv2.setNumThreads(0)
def files(d, legacy=False):
    fs = glob.glob(os.path.join(d, "*.exr"))
    key = (lambda f: int(re.findall(r"(\d+)", os.path.basename(f))[-2])) if legacy \
          else (lambda f: int(re.search(r"\.(\d+)\.exr$", f).group(1)))
    return sorted(fs, key=key)
def rd(f):
    return cv2.resize(cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2),
                      (1280, 720), interpolation=cv2.INTER_AREA)
# Identical compression for both builds: scale by the SEQUENCE mean (one scalar, so temporal
# variation survives) then x/(1+x). Raw HDR is firefly-dominated and must never be measured directly.
def row(label, d, legacy=False):
    fs = files(d, legacy)
    if not fs: print("%-32s (no frames)" % label, flush=True); return
    g = [rd(f) for f in fs]
    mu = float(np.mean([x.mean() for x in g]))
    g = [(x/mu)/(1.0+(x/mu)) for x in g]
    m2 = float(np.mean([x.mean() for x in g]))
    o = []
    for s in (16, 64):
        b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
        o.append(1e3*float(np.mean([np.abs(b[i]-2*b[i-1]+b[i-2]).mean() for i in range(2, len(b))]))/m2)
    gm = np.array([x.mean() for x in g])
    gl = 1e3*float(np.abs(gm[2:]-2*gm[1:-1]+gm[:-2]).mean())/m2
    print("%-32s %5d %9.2f %9.2f %10.3f" % (label, len(g), o[0], o[1], gl), flush=True)
print("%-32s %5s %9s %9s %10s" % ("OptiX HDR output, no tonemap", "n", "s=16", "s=64", "global"), flush=True)
row("legacy (HDR model, no TAA)", "../legacy/outputs/Bistro_OptixHDR_Video", True)
row("v8 legacy-matched (same cfg)", "orbit_optixhdr_lm")
