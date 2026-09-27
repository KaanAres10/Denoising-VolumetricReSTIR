"""ReSTIR in both engines against brute-force path tracing at the verify pose (run.sh captures).
   score.py [run tag ...]      (default: v9_restir fork_restir)

Everything is on luminance. Captures come every L frames (L = FRAMES / CAPTURES); the AccumulatePass averages
A_k at them give the mean of each L-frame WINDOW, W_k = k A_k - (k-1) A_(k-1).

Reference: each engine's own (8192 frames x 16 spp); the two are compared first, and differ slightly at low
frequency (the scenes' material/emission models), so a run is never scored against the other engine's. Its noise per pixel ~ (first half - second half)^2 / 4, which is taken off every MSE.

Bias: the second half of a run's windows (history warmed up), region mean against R. Error bar: the scatter
of the window means / sqrt(windows). Fireflies make that scatter heavy-tailed, so the median window is printed
too -- NOT an unbiased estimate, a robust one: it tells what the image is without the rare events.

One frame: the raw frames captured in the second half. MSE / mean(R)^2 with the worst 0.01% of pixels left out
(per-pixel MSE is 95-100% those pixels in both engines, i.e. a firefly count, not image quality), and at blur
2 and 8 on frames clamped to luminance 1 (the lamp glass is 0.41) so one firefly does not become a blob.

Fireflies: pixel-windows whose window mean exceeds 1 / 10 (a normal pixel is ~0.0005-0.01), excluding pixels
that are the same in every window (directly visible emitters), by region."""
import os; os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import glob, re, sys
import cv2, numpy as np
cv2.setNumThreads(0)
C = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cap")
# A run is "tag" (scored against its own engine's reference) or "tag@ref" (e.g. v9bvh_restir_long@v9bvh:
# against cap/v9bvh_ref).
TAGS = sys.argv[1:] or ["v9_restir", "fork_restir"]
REF_OF = {t.split("@")[0]: t.split("@")[1] for t in TAGS if "@" in t}
TAGS = [t.split("@")[0] + ("@" + t.split("@")[1] if "@" in t else "") for t in TAGS]
REG = {"plume core": np.s_[250:700, 900:1150], "street": np.s_[800:1080, 0:700], "facade": np.s_[0:300, 0:700],
       "cafe": np.s_[300:800, 1550:1920], "lamp+plume": np.s_[100:1080, 800:1600], "whole": np.s_[:, :]}
Y = np.array([0.0722, 0.7152, 0.2126])  # BGR
BAD = np.zeros((1080, 1920), bool)      # non-finite anywhere (the fork's half-float files overflow on the lamp glass)

def load(p):
    x = cv2.imread(p, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float64)
    bad = ~np.isfinite(x).all(-1); BAD[bad] = True; x[bad] = 0
    return x @ Y

def captures(tag, output):
    d = os.path.join(C, tag); out = {}
    if tag.startswith("fork"):
        for p in glob.glob(os.path.join(d, "*.%s.0.exr" % output)):
            out[int(re.search(r"_(\d+)\.%s" % re.escape(output), os.path.basename(p)).group(1))] = p
    else:
        order = [int(l.split()[0]) for l in open(os.path.join(d, tag + ".frames.txt")) if not l.startswith("first")]
        for p in glob.glob(os.path.join(d, "*.%s.*.exr" % output)):
            fr = int(re.search(r"\.(\d+)\.exr$", p).group(1))
            if fr in order: out[order.index(fr) + 1] = p
    return out

def windows(tag):
    a = captures(tag, "Accum.output"); A = {k: load(a[k]) for k in sorted(a)}
    return [A[1]] + [k * A[k] - (k - 1) * A[k - 1] for k in range(2, max(A) + 1)]

def blur(x, s): return cv2.GaussianBlur(x, (0, 0), s) if s else x

# Reference.
refs = {}
for e in ["v9", "fork"] + sorted(set(REF_OF.values()) - {"v9", "fork"}):
    a = captures(e + "_ref", "Accum.output") if os.path.isdir(os.path.join(C, e + "_ref")) else {}
    if len(a) >= 8:
        K = max(a); first = load(a[K // 2]); full = load(a[K]); refs[e] = (full, first, 2 * full - first)
if "v9" in refs and "fork" in refs:
    print("References agree? fork against 9.0, 8192 frames x 16 spp each:")
    for s in (0, 2, 8):
        d = np.mean((blur(refs["fork"][0], s) - blur(refs["v9"][0], s)) ** 2)
        n = sum(np.mean((blur(r[1], s) - blur(r[2], s)) ** 2) / 4 for r in refs.values())
        print("  blur %d: mean squared difference %.3e, the two references' own noise %.3e, ratio %.2f" % (s, d, n, d / n))
    print("  region means, fork / 9.0 - 1: " + "  ".join("%s %+.2f%%" % (r, 100 * (refs["fork"][0][s].mean() / refs["v9"][0][s].mean() - 1)) for r, s in REG.items()))
# The two engines' scenes differ slightly (the references disagree beyond their noise at low frequency: the
# fork's cafe is ~1% brighter -- material/emission models), so each run is scored against its OWN engine's.
REF = lambda tag: refs[tag.split("@")[1] if "@" in tag else ("fork" if tag.startswith("fork") else "v9")]

runs = {}
for tag in TAGS:
    base = tag.split("@")[0]; W = windows(base); raw = captures(base, "VolumetricReSTIR.accumulated_color")
    runs[tag] = (W, [load(raw[k]) for k in sorted(raw) if k > len(W) // 2])
for x in [x for r in refs.values() for x in r] + [w for W, F in runs.values() for w in W + F]:
    x[BAD] = 0
print("pixels left out (non-finite in some capture): %d" % BAD.sum())

print("\nBias, second half of each run against the reference: mean ± error | median window")
print("%-20s" % "" + "".join("%24s" % r for r in REG))
for tag, (W, F) in runs.items():
    R = REF(tag)[0]; h = W[len(W) // 2:]; cells = []
    for s in REG.values():
        v = np.array([w[s].mean() for w in h]) / R[s].mean() - 1
        cells.append("%+6.2f%% ±%5.2f | %+5.2f%%" % (100 * v.mean(), 100 * v.std(ddof=1) / np.sqrt(len(v)), 100 * np.median(v)))
    print("%-20s" % tag + "".join("%24s" % c for c in cells))

print("\nOne frame against the reference, MSE / mean(R)^2, reference noise removed:")
print("%-20s %8s %12s %12s %12s %8s" % ("", "frames", "trimmed", "blur 2 clamp", "blur 8 clamp", "black %"))
def refvar(tag, s, trim=None):
    Ra, Rb = REF(tag)[1:]
    d = (blur(Ra, s) - blur(Rb, s)) ** 2 / 4
    return np.sort(d.ravel())[:-(d.size // 10000)].mean() if trim else d.mean()
for tag, (W, F) in runs.items():
    R = REF(tag)[0]; mu2 = R.mean() ** 2; refvar_ = lambda s, trim=None: refvar(tag, s, trim)
    tr = []
    for f in F:
        d2 = np.sort(((f - R) ** 2).ravel()); tr.append(d2[:-(d2.size // 10000)].mean())
    bl = [np.mean([(blur(np.minimum(f, 1.0), s) - blur(np.minimum(R, 1.0), s)) ** 2 for f in F]) for s in (2, 8)]
    print("%-20s %8d %12.5f %12.6f %12.7f %8.1f   (reference's own noise %.5f / %.6f / %.7f)" % (tag, len(F), (np.mean(tr) - refvar_(0, True)) / mu2,
          (bl[0] - refvar_(2)) / mu2, (bl[1] - refvar_(8)) / mu2, 100 * np.mean([(f <= 0).mean() for f in F]),
          refvar_(0, True) / mu2, refvar_(2) / mu2, refvar_(8) / mu2))

print("\nFireflies: pixel-windows with window mean > 1 / > 10 (all windows), by region; largest window mean")
for tag, (W, F) in runs.items():
    st = np.stack(W); const = st.std(0) < 1e-4 * np.maximum(st.mean(0), 1e-9)
    L = [np.where(const, 0, w) for w in W]
    cnt = lambda t, s: sum(int((w[s] > t).sum()) for w in L)
    print("%-20s %d windows: " % (tag, len(W)) + "  ".join("%s %d/%d" % (r, cnt(1, s), cnt(10, s)) for r, s in REG.items()) + "   max %.1f" % max(w.max() for w in L))
