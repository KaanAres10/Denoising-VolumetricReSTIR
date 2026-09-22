import glob, os, re, cv2, numpy as np
def frames(d, ext="png"):
    fs = glob.glob(os.path.join(d, "*." + ext))
    def idx(f):
        m = re.findall(r"(\d+)", os.path.basename(f))
        return int(m[-2]) if d.startswith("../legacy") else int(re.search(r"\.(\d+)\."+ext+"$", f).group(1))
    return sorted(fs, key=idx)
rows = [("legacy OptiX (colour only)", frames("../legacy/outputs/Bistro_Optix_Video")),
        ("v8 OptiX (colour only)",     frames("orbit_optix")),
        ("v8 OptiX + volume guides",   frames("orbit_optix_guides"))]
picks = [0, 75, 150, 225]
W = 460
out = []
for label, fs in rows:
    print(label, len(fs))
    band = []
    for p in picks:
        im = cv2.imread(fs[p], cv2.IMREAD_UNCHANGED)[..., :3]
        h, w = im.shape[:2]
        im = cv2.resize(im, (W, int(h * W / w)), interpolation=cv2.INTER_AREA)
        band.append(im)
    band = np.hstack(band)
    strip = np.zeros((26, band.shape[1], 3), np.uint8)
    cv2.putText(strip, label, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,255), 1, cv2.LINE_AA)
    out.append(np.vstack([strip, band]))
cv2.imwrite("_cmp_optix.png", np.vstack(out))
print("wrote _cmp_optix.png")
