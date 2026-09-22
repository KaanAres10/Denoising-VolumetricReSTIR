import glob, os, re
import cv2, numpy as np
def load(d):
    fs = sorted(glob.glob(os.path.join(d, "*.png")),
                key=lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))
    return [cv2.resize(cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2)/255.0,
                       (1280, 720), interpolation=cv2.INTER_AREA) for f in fs]
def row(label, d):
    g = load(d); mu = float(np.mean([x.mean() for x in g])); o = []
    for s in (32, 128):
        b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
        o.append(1e3*float(np.mean([np.abs(b[i]-2*b[i-1]+b[i-2]).mean() for i in range(2,len(b))]))/mu)
    m = np.array([x.mean() for x in g]); gl = 1e3*float(np.abs(m[2:]-2*m[1:-1]+m[:-2]).mean())/mu
    sh = float(np.mean([cv2.Laplacian(x*255.0, cv2.CV_32F).var() for x in g]))
    print("%-40s %8.2f %8.2f %12.4f %11.1f" % (label, o[0], o[1], gl, sh))
print("%-40s %8s %8s %12s %11s" % ("OptiX, 300 frames @1080p", "s=32", "s=128", "whole-frame", "sharpness"))
row("colour only (shipped)", "orbit_optix")
row("+ volume-aware albedo/normal guides", "orbit_optix_guides")
row("RELAX (reference)", "orbit_relax")
