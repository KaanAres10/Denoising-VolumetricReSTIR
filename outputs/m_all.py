import glob, os, re, cv2, numpy as np
def load(d, ext="png", legacy=False):
    fs = glob.glob(os.path.join(d, "*." + ext))
    key = (lambda f: int(re.findall(r"(\d+)", os.path.basename(f))[-2])) if legacy \
          else (lambda f: int(re.search(r"\.(\d+)\." + ext + "$", f).group(1)))
    fs = sorted(fs, key=key)
    return [cv2.resize(cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2)/255.0,
                       (1280, 720), interpolation=cv2.INTER_AREA) for f in fs]
def row(label, d, legacy=False):
    g = load(d, legacy=legacy)
    mu = float(np.mean([x.mean() for x in g]))
    o = []
    for s in (32, 128):
        b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
        o.append(1e3*float(np.mean([np.abs(b[i]-2*b[i-1]+b[i-2]).mean() for i in range(2, len(b))]))/mu)
    # contrast-normalised sharpness: divide each frame by the sequence mean first, so the two builds'
    # different tonemappers (legacy Linear+autoexposure vs v8 fixed +8 EV) cancel instead of being
    # measured as detail.
    sh = float(np.mean([cv2.Laplacian(x/mu, cv2.CV_32F).var() for x in g]))
    print("%-34s %8.2f %8.2f %11.2f" % (label, o[0], o[1], sh))
print("%-34s %8s %8s %11s" % ("bistro orbit, 300 frames", "s=32", "s=128", "detail"))
row("legacy OptiX (colour only)", "../legacy/outputs/Bistro_Optix_Video", legacy=True)
row("v8 OptiX (colour only)", "orbit_optix")
row("v8 OptiX + volume guides", "orbit_optix_guides")
row("v8 RELAX (reference)", "orbit_relax")
