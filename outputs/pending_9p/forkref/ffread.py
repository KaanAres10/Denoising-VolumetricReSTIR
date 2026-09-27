"""Read the VR_FF_DEBUG captures at the firefly pixels.   ffread.py <tag> <mode> frame:x,y ..."""
import os; os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import glob, re, sys, cv2, numpy as np
NAMES = {1: ("F", "p_y", "W"), 2: ("runningSum", "M", "depth"), 3: ("lightID", "F p_hat-style", "final lum"), 4: ("F spatial opts", "F spatial, mip 0", "F spatial, t-step 0.2"), 5: ("Tv analytic", "Tl analytic", "light distance"), 6: ("Tv ray-marched", "Tl ray-marched", "Le cos/d^2"), 7: ("Tr", "steps+1e3*negInt+1e6*negT", "anti-depth"), 8: ("worst seg depth", "its t_dist", "min t_dist"), 9: ("worst p0.x", "p0.y", "p0.z"), 10: ("worst p1.x", "p1.y", "p1.z"), 11: ("tSide.x", "tSide.y", "tSide.z"), 12: ("dda dir.x", "dir.y", "dir.z"), 13: ("adapter t", "dda t.x", "dda t.y"), 14: ("mask x+2y+4z", "tFar", "maxDeltaT"), 15: ("world dir.x", "dir.y", "dir.z"), 16: ("scatter y", "light y", "voxel-space dir.y"), 18: ("light distance", "cos at light", "BSDF*cos"), 19: ("cos at surface", "Le lum", "light ID")}
tag, mode = sys.argv[1], int(sys.argv[2]); d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cap", tag)
fr = {int(l.split()[0]): int(l.split()[1]) for l in open(os.path.join(d, tag + ".frames.txt")) if not l.startswith("first")}
want = {int(a.split(":")[0]): tuple(map(int, a.split(":")[1].split(","))) for a in sys.argv[3:]}
for p in glob.glob(os.path.join(d, "*.accumulated_color.*.exr")):
    n = fr[int(re.search(r"\.(\d+)\.exr$", p).group(1))]
    if n not in want: continue
    x = cv2.imread(p, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float64)[..., ::-1]
    px, py = want[n]
    print("mode %d frame %d (%d,%d): " % (mode, n, px, py) + "  ".join("%s %.9g" % (k, v) for k, v in zip(NAMES[mode], x[py, px])))
