import glob, os, re, cv2, numpy as np
# The orbit's centre IS the camera target, so the plume sits at the image centre in every frame.
# A centred crop is therefore a plume-dominant region without needing a per-frame mask.
CX0, CX1, CY0, CY1 = 0.34, 0.66, 0.05, 0.95
def nth(d, n, legacy=False):
    fs = glob.glob(os.path.join(d, "*.png"))
    key = (lambda f: int(re.findall(r"(\d+)", os.path.basename(f))[-2])) if legacy \
          else (lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))
    return sorted(fs, key=key)[n]
im = cv2.imread(nth("orbit_optix", 150), cv2.IMREAD_UNCHANGED)[..., :3]
h, w = im.shape[:2]
x0, x1, y0, y1 = int(CX0*w), int(CX1*w), int(CY0*h), int(CY1*h)
vis = im.copy(); cv2.rectangle(vis, (x0, y0), (x1, y1), (0, 255, 255), 4)
cv2.imwrite("_crop_check.png", cv2.resize(vis, (900, int(900*h/w))))
print("crop", x0, x1, y0, y1)
