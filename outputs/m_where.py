import glob, os, re, cv2, numpy as np
# Split the frame into the plume-dominant centre (the orbit centre IS the camera target, so the smoke
# sits at the image centre every frame) and everything else, and score them separately. If the gap
# between the builds lives in the centre it is volumetric; if it lives outside, it is the surface path.
CX0, CX1, CY0, CY1 = 0.34, 0.66, 0.05, 0.95
def load(d, legacy=False):
    fs = glob.glob(os.path.join(d, "*.png"))
    key = (lambda f: int(re.findall(r"(\d+)", os.path.basename(f))[-2])) if legacy \
          else (lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))
    return [cv2.resize(cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2)/255.0,
                       (1280, 720), interpolation=cv2.INTER_AREA) for f in sorted(fs, key=key)]
def score(g, mask):
    mu = float(np.mean([x[mask].mean() for x in g]))
    b = [cv2.GaussianBlur(x, (0, 0), 16) for x in g]
    d = np.mean([np.abs(b[i]-2*b[i-1]+b[i-2])[mask].mean() for i in range(2, len(b))])
    return 1e3*float(d)/mu
def row(label, d, legacy=False):
    if not glob.glob(os.path.join(d, "*.png")):
        print("%-38s (no frames)" % label, flush=True); return
    g = load(d, legacy)
    h, w = g[0].shape
    inner = np.zeros((h, w), bool)
    inner[int(CY0*h):int(CY1*h), int(CX0*w):int(CX1*w)] = True
    print("%-38s %5d %10.2f %10.2f" % (label, len(g), score(g, inner), score(g, ~inner)), flush=True)
print("%-38s %5s %10s %10s" % ("", "n", "plume", "surfaces"), flush=True)
row("legacy OptiX", "../legacy/outputs/Bistro_Optix_Video", True)
row("v8 legacy-matched", "orbit_optix_legacymatch")
row("v8 shipped (mvec+TAA)", "orbit_optix")
