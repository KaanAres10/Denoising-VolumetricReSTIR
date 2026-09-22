import glob, os, re, cv2, numpy as np
cv2.setNumThreads(0)
def load(d):
    got = []
    for f in glob.glob(d + "/*.png"):
        b = os.path.basename(f)
        m = re.search(r"_(\d{4})\.", b) or re.search(r"\.(\d+)\.png$", b)
        if m: got.append((int(m.group(1)), f))
    fs = [f for _, f in sorted(got)]
    return [cv2.resize(cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2)/255.0,
                       (1280, 720), interpolation=cv2.INTER_AREA) for f in fs]
def row(label, d):
    if not glob.glob(d + "/*.png"):
        print("%-38s (no frames)" % label, flush=True); return
    g = load(d)
    h, w = g[0].shape
    inner = np.zeros((h, w), bool); inner[int(0.05*h):int(0.95*h), int(0.34*w):int(0.66*w)] = True
    def sc(mask, s):
        mu = float(np.mean([x[mask].mean() for x in g]))
        b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
        return 1e3*float(np.mean([np.abs(b[i]-2*b[i-1]+b[i-2])[mask].mean() for i in range(2, len(b))]))/mu
    mu = float(np.mean([x.mean() for x in g]))
    det = float(np.mean([np.abs(x-cv2.GaussianBlur(x,(0,0),2)).mean() for x in g]))/mu
    print("%-38s %4d %8.2f %9.2f %10.2f %8.4f"
          % (label, len(g), sc(np.ones((h,w),bool), 32), sc(inner,16), sc(~inner,16), det), flush=True)
print("%-38s %4s %8s %9s %10s %8s" % ("", "n", "s=32", "plume", "surfaces", "detail"), flush=True)
row("legacy Aug-13 (OptiX 9.0 build)", "../legacy/outputs/Bistro_Optix_Video")
row("legacy TODAY (same binary)", "../legacy/outputs/Bistro_Optix_Today")
row("v8 legacy-matched", "orbit_optix_legacymatch")
