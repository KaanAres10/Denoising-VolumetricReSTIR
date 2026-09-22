import glob, os, re, sys, cv2, numpy as np
# Plume-only metric. The orbit centre IS the camera target, so the plume sits at the image centre in
# every frame; a centred crop is a plume-dominant region without needing a per-frame mask. Measuring
# the whole frame instead lets Bistro's surfaces -- which are most of the pixels -- dominate the score,
# and the question here is specifically about the smoke.
CX0, CX1, CY0, CY1 = 0.34, 0.66, 0.05, 0.95
def load(d, legacy=False):
    fs = glob.glob(os.path.join(d, "*.png"))
    key = (lambda f: int(re.findall(r"(\d+)", os.path.basename(f))[-2])) if legacy \
          else (lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))
    out = []
    for f in sorted(fs, key=key):
        im = cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2) / 255.0
        h, w = im.shape[:2]
        im = im[int(CY0*h):int(CY1*h), int(CX0*w):int(CX1*w)]
        out.append(cv2.resize(im, (410, 648), interpolation=cv2.INTER_AREA))
    return out
def row(label, d, legacy=False):
    if not glob.glob(os.path.join(d, "*.png")):
        print("%-38s %s" % (label, "(no frames)")); return
    g = load(d, legacy)
    mu = float(np.mean([x.mean() for x in g])); o = []
    for s in (8, 32):
        b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
        o.append(1e3*float(np.mean([np.abs(b[i]-2*b[i-1]+b[i-2]).mean() for i in range(2, len(b))]))/mu)
    sh = float(np.mean([cv2.Laplacian(x/mu, cv2.CV_32F).var() for x in g]))
    print("%-38s %5d %8.2f %8.2f %8.3f" % (label, len(g), o[0], o[1], sh))
print("%-38s %5s %8s %8s %8s" % ("plume crop", "n", "s=8", "s=32", "detail"))
for label, d, lg in [
    ("legacy OptiX", "../legacy/outputs/Bistro_Optix_Video", True),
    ("v8 OptiX (mvec+TAA, shipped)", "orbit_optix", False),
    ("v8 OptiX legacy-matched", "orbit_optix_legacymatch", False),
    ("v8 OptiX legacy-matched + frozen", "orbit_optix_legacymatch_froz", False),
    ("v8 OptiX + guides", "orbit_optix_guides", False),
]:
    row(label, d, lg)
