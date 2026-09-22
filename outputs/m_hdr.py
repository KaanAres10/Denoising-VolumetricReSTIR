import glob, os, re, cv2, numpy as np
cv2.setNumThreads(0)
def files(d, legacy=False):
    fs = glob.glob(os.path.join(d, "*.exr"))
    key = (lambda f: int(re.findall(r"(\d+)", os.path.basename(f))[-2])) if legacy \
          else (lambda f: int(re.search(r"\.(\d+)\.exr$", f).group(1)))
    return sorted(fs, key=key)
def rd(f):
    im = cv2.imread(f, cv2.IMREAD_UNCHANGED)
    if im is None: raise IOError(f)
    im = im[..., :3].astype(np.float32)
    return cv2.resize(im.mean(axis=2), (1280, 720), interpolation=cv2.INTER_AREA)

# --- Estimator test: spatial noise of the RAW output, on the 4 frames legacy captured.
# High-frequency energy per frame, normalised by the frame's own mean, so the two builds'
# absolute radiance scales cancel and what is left is relative noise.
print("=== raw estimator, spatial noise (relative high-frequency energy) ===", flush=True)
lg, v8 = files("../legacy/outputs/Bistro_Raw_Video", True), files("orbit_raw_v8")
for i in range(min(4, len(lg))):
    a, b = rd(lg[i]), rd(v8[i])
    def hf(x):
        x = x / max(1e-9, float(x.mean()))
        return float(np.abs(x - cv2.GaussianBlur(x, (0, 0), 2)).mean())
    print("  frame %d   legacy %.4f   v8 %.4f   ratio %.2fx" % (i, hf(a), hf(b), hf(b)/hf(a)), flush=True)

# --- Denoiser test: temporal instability of the HDR denoiser output, 300 frames each.
# HDR is firefly-dominated, so compress identically first: scale each sequence by its own mean
# (one scalar, so temporal variation survives) then x/(1+x).
print("=== OptiX HDR denoiser output, temporal instability ===", flush=True)
for label, d, legacy in [("legacy", "../legacy/outputs/Bistro_OptixHDR_Video", True),
                         ("v8", "orbit_optixhdr_v8", False)]:
    fs = files(d, legacy)
    g = [rd(f) for f in fs]
    mu = float(np.mean([x.mean() for x in g]))
    g = [x / mu for x in g]
    g = [x / (1.0 + x) for x in g]
    m2 = float(np.mean([x.mean() for x in g]))
    out = []
    for s in (16, 64):
        b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
        out.append(1e3*float(np.mean([np.abs(b[i]-2*b[i-1]+b[i-2]).mean() for i in range(2, len(b))]))/m2)
    print("  %-8s n=%d  s=16 %8.2f   s=64 %8.2f" % (label, len(g), out[0], out[1]), flush=True)
