import glob, os, re, cv2, numpy as np
cv2.setNumThreads(0)
# A frame with the volume missing is nearly black with a few emitter dots. A frame WITH the plume has
# a large mid-tone region near the image centre (the orbit centre is the camera target, so the smoke
# is always centred). Score = fraction of centre pixels in a mid-tone band -- emitters are blown out
# and the empty street is near black, so only smoke lands in the band.
def scan(label, d, ext, legacy=False):
    fs = glob.glob(os.path.join(d, "*." + ext))
    if not fs: print("%-34s (no frames)" % label, flush=True); return
    key = (lambda f: int(re.findall(r"(\d+)", os.path.basename(f))[-2])) if legacy \
          else (lambda f: int(re.search(r"\.(\d+)\." + ext + "$", f).group(1)))
    fs = sorted(fs, key=key)
    fr = []
    for f in fs:
        im = cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32)
        if ext == "png": im /= 255.0
        else:            im = im / max(1e-9, float(np.percentile(im, 99.5)))  # normalise HDR
        g = im.mean(axis=2)
        h, w = g.shape
        c = g[int(0.05*h):int(0.95*h), int(0.34*w):int(0.66*w)]
        fr.append(float(((c > 0.08) & (c < 0.95)).mean()))
    fr = np.array(fr)
    bad = int((fr < 0.10).sum())
    print("%-34s n=%3d  midtone-centre: median %.3f  min %.3f  frames<0.10: %d"
          % (label, len(fr), float(np.median(fr)), float(fr.min()), bad), flush=True)
for label, d, ext, lg in [
    ("legacy OptiX (LDR)", "../legacy/outputs/Bistro_Optix_Video", "png", True),
    ("legacy OptiX (HDR)", "../legacy/outputs/Bistro_OptixHDR_Video", "exr", True),
    ("v8 shipped", "orbit_optix", "png", False),
    ("v8 legacy-matched", "orbit_optix_legacymatch", "png", False),
    ("v8 legacy-matched FROZEN", "orbit_optix_legacymatch_froz", "png", False),
    ("v8 HDR legacy-matched", "orbit_optixhdr_lm", "exr", False),
    ("v8 RAW", "orbit_raw_v8", "exr", False),
    ("v8 + guides", "orbit_optix_guides", "png", False),
]:
    scan(label, d, ext, lg)
