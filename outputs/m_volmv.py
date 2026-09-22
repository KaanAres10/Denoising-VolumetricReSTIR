import glob, os, re, cv2, numpy as np
cv2.setNumThreads(0)
CX0, CX1, CY0, CY1 = 0.34, 0.66, 0.05, 0.95
def load(d):
    fs = sorted(glob.glob(os.path.join(d, "*.png")),
                key=lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))
    return [cv2.resize(cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2)/255.0,
                       (1280, 720), interpolation=cv2.INTER_AREA) for f in fs]
def sc(g, mask, s):
    mu = float(np.mean([x[mask].mean() for x in g]))
    b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
    return 1e3*float(np.mean([np.abs(b[i]-2*b[i-1]+b[i-2])[mask].mean() for i in range(2, len(b))]))/mu
def row(label, d):
    if not glob.glob(os.path.join(d, "*.png")):
        print("%-34s (no frames)" % label, flush=True); return
    g = load(d); h, w = g[0].shape
    inner = np.zeros((h, w), bool); inner[int(CY0*h):int(CY1*h), int(CX0*w):int(CX1*w)] = True
    mu = float(np.mean([x.mean() for x in g]))
    full = sc(g, np.ones((h, w), bool), 32)
    sh = float(np.mean([cv2.Laplacian(x/mu, cv2.CV_32F).var() for x in g]))
    print("%-34s %8.2f %9.2f %10.2f %8.3f"
          % (label, full, sc(g, inner, 16), sc(g, ~inner, 16), sh), flush=True)
print("%-34s %8s %9s %10s %8s" % ("shipped config, one knob changed", "s=32", "plume", "surfaces", "detail"), flush=True)
row("baseline (gbuffer mvec)", "orbit_optix")
row("+ volume-aware mvec", "orbit_optix_volmv")
row("+ volume guides", "orbit_optix_guides")
row("+ volume mvec + guides", "orbit_optix_volmv_guides")
