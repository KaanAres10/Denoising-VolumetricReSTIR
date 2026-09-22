# RR2 (310.9.1 preset F) against the previous Ray Reconstruction (310.7.0 preset E), bistro orbit.
#
# Same metric as m_denoisers.py / m_volmv_all.py, so the rows are comparable with STATE.md: frames
# downscaled to 1280x720 grey; instability = mean |second temporal difference| of blurred frames,
# normalised by mean brightness (lower = steadier); detail = mean |x - blur(x, 2)| / mean (higher =
# more high-frequency energy, which noise inflates too).
#
# Plus what a two-version comparison needs and a single table cannot show: per-frame differences
# between RUNS. RR carries temporal history under a jittered camera and takes a wall-clock frame-time
# hint, so two runs of one configuration are not identical. The run-vs-run difference of a
# configuration against itself is the noise floor; a config-vs-config difference means something only
# above it.
import glob, os, re, sys
from concurrent.futures import ThreadPoolExecutor
import cv2, numpy as np

cv2.setNumThreads(0)
HERE = os.path.dirname(os.path.abspath(__file__))


def load(d):
    got = []
    for f in glob.glob(os.path.join(HERE, d, "*.png")):
        m = re.search(r"\.(\d+)\.png$", os.path.basename(f))
        if m:
            got.append((int(m.group(1)), f))
    got.sort()

    def rd(f):
        im = cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2) / 255.0
        return cv2.resize(im, (1280, 720), interpolation=cv2.INTER_AREA)

    with ThreadPoolExecutor(16) as ex:
        return [i for i, _ in got], list(ex.map(rd, [f for _, f in got]))


RUNS = [
    ("310.7.0 E, pre-upgrade build", "rr2_pre_E"),
    ("310.7.0 E  run 1", "rr2_prev_E_r1"),
    ("310.7.0 E  run 2", "rr2_prev_E_r2"),
    ("310.9.1 E", "rr2_cur_E"),
    ("310.9.1 Default", "rr2_cur_Default"),
    ("310.9.1 F (RR2) run 1", "rr2_cur_F_r1"),
    ("310.9.1 F (RR2) run 2", "rr2_cur_F_r2"),
    # DLSSDGuides skyDefaults on (the default since 2026-09-18): no NaN normals on no-geometry pixels.
    ("310.7.0 E, sky guides fixed", "rr2s_prev_E"),
    ("310.9.1 F (RR2), sky guides fixed", "rr2s_cur_F"),
]

data = {}
for label, d in RUNS:
    if glob.glob(os.path.join(HERE, d, "*.png")):
        data[d] = load(d)

g0 = next(iter(data.values()))[1][0]
h, w = g0.shape
inner = np.zeros((h, w), bool)
inner[int(0.05 * h):int(0.95 * h), int(0.34 * w):int(0.66 * w)] = True
full = np.ones((h, w), bool)


def score(g, mask, s):
    mu = float(np.mean([x[mask].mean() for x in g]))
    b = [cv2.GaussianBlur(x, (0, 0), s) for x in g]
    return 1e3 * float(np.mean([np.abs(b[i] - 2 * b[i - 1] + b[i - 2])[mask].mean() for i in range(2, len(b))])) / mu


print("%-30s %4s %7s %7s %9s %8s %8s %8s" % ("bistro orbit, 1080p", "n", "s=32", "plume", "surfaces",
                                              "detail", "plumeDet", "mean"))
for label, d in RUNS:
    if d not in data:
        print("%-30s (no frames)" % label)
        continue
    _, g = data[d]
    mu = float(np.mean([x.mean() for x in g]))
    det = float(np.mean([np.abs(x - cv2.GaussianBlur(x, (0, 0), 2)).mean() for x in g])) / mu
    detp = float(np.mean([np.abs(x - cv2.GaussianBlur(x, (0, 0), 2))[inner].mean() for x in g])) / mu
    print("%-30s %4d %7.2f %7.2f %9.2f %8.4f %8.4f %8.4f"
          % (label, len(g), score(g, full, 32), score(g, inner, 16), score(g, ~inner, 16), det, detp, mu),
          flush=True)

PAIRS = [
    ("noise floor", "rr2_prev_E_r1", "rr2_prev_E_r2"),
    ("noise floor", "rr2_cur_F_r1", "rr2_cur_F_r2"),
    ("lib swap (should be ~floor)", "rr2_pre_E", "rr2_prev_E_r1"),
    ("lib swap (should be ~floor)", "rr2_pre_E", "rr2_prev_E_r2"),
    ("Default == F ?", "rr2_cur_Default", "rr2_cur_F_r1"),
    ("Default == F ?", "rr2_cur_Default", "rr2_cur_F_r2"),
    ("E: 310.9.1 vs 310.7.0", "rr2_cur_E", "rr2_prev_E_r1"),
    ("E: 310.9.1 vs 310.7.0", "rr2_cur_E", "rr2_prev_E_r2"),
    ("RR2 vs previous", "rr2_cur_F_r1", "rr2_prev_E_r1"),
    ("RR2 vs previous", "rr2_cur_F_r2", "rr2_prev_E_r2"),
    ("sky fix, effect on E", "rr2s_prev_E", "rr2_prev_E_r1"),
    ("sky fix, effect on RR2", "rr2s_cur_F", "rr2_cur_F_r1"),
    ("RR2 vs previous, sky fixed", "rr2s_cur_F", "rr2s_prev_E"),
]
print()
print("%-28s %-17s %-17s %9s %9s %8s %9s" % ("per-frame difference", "a", "b", "mean|d|", "plume|d|",
                                              "%px>2", "mean a/b"))
for what, a, b in PAIRS:
    if a not in data or b not in data:
        continue
    ia, ga = data[a]
    ib, gb = data[b]
    common = sorted(set(ia) & set(ib))
    pa = {i: x for i, x in zip(ia, ga)}
    pb = {i: x for i, x in zip(ib, gb)}
    d_all = [np.abs(pa[i] - pb[i]) for i in common]
    mad = 255.0 * float(np.mean([x.mean() for x in d_all]))
    madp = 255.0 * float(np.mean([x[inner].mean() for x in d_all]))
    frac = 100.0 * float(np.mean([(x > 2.0 / 255.0).mean() for x in d_all]))
    ratio = float(np.mean([pa[i].mean() for i in common])) / float(np.mean([pb[i].mean() for i in common]))
    short = lambda s: s.replace("rr2s_", "sky_").replace("rr2_", "")
    print("%-28s %-17s %-17s %9.3f %9.3f %8.2f %9.4f" % (what, short(a), short(b), mad, madp, frac, ratio))
