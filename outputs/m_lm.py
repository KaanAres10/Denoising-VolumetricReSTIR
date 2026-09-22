import glob, os, re, sys, cv2, numpy as np
def load(d, legacy=False):
    fs = glob.glob(os.path.join(d, "*.png"))
    key = (lambda f: int(re.findall(r"(\d+)", os.path.basename(f))[-2])) if legacy \
          else (lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))
    return [cv2.resize(cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2)/255.0,
                       (1280, 720), interpolation=cv2.INTER_AREA) for f in sorted(fs, key=key)]
def row(label, d, legacy=False):
    if not glob.glob(os.path.join(d, "*.png")):
        print("%-38s (no frames)" % label, flush=True); return
    g = load(d, legacy)
    mu = float(np.mean([x.mean() for x in g])); o = []
    for s in (32, 128):
        b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
        o.append(1e3*float(np.mean([np.abs(b[i]-2*b[i-1]+b[i-2]).mean() for i in range(2, len(b))]))/mu)
    m = np.array([x.mean() for x in g])
    gl = 1e3*float(np.abs(m[2:]-2*m[1:-1]+m[:-2]).mean())/mu
    sh = float(np.mean([cv2.Laplacian(x/mu, cv2.CV_32F).var() for x in g]))
    print("%-38s %5d %8.2f %8.2f %10.3f %8.3f" % (label, len(g), o[0], o[1], gl, sh), flush=True)
print("%-38s %5s %8s %8s %10s %8s" % ("", "n", "s=32", "s=128", "global", "detail"), flush=True)
row("legacy OptiX", "../legacy/outputs/Bistro_Optix_Video", True)
row("v8 legacy-matched", "orbit_optix_legacymatch")
row("v8 legacy-matched + frozen scene", "orbit_optix_legacymatch_froz")
