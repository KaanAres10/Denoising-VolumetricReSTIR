import glob, os, re, cv2, numpy as np
cv2.setNumThreads(0)
def files(d, legacy=False):
    fs = glob.glob(os.path.join(d, "*.exr"))
    key = (lambda f: int(re.findall(r"(\d+)", os.path.basename(f))[-2])) if legacy \
          else (lambda f: int(re.search(r"\.(\d+)\.exr$", f).group(1)))
    return sorted(fs, key=key)
def rd(f):
    return cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2)
lg, v8 = files("../legacy/outputs/Bistro_Raw_Video", True), files("orbit_raw_v8")
print("%-6s %-8s %10s %10s %10s %10s" % ("frame", "build", "mean", "p99.9", "max", ">100xmean"), flush=True)
for i in range(4):
    for label, f in (("legacy", lg[i]), ("v8", v8[i])):
        x = rd(f); mu = float(x.mean())
        print("%-6d %-8s %10.4f %10.2f %10.1f %9.4f%%"
              % (i, label, mu, float(np.percentile(x, 99.9)), float(x.max()),
                 100.0*float((x > 100*mu).mean())), flush=True)
