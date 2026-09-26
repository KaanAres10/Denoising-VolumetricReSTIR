"""Pin firefly pixels to their frames from a VR_CAPTURE_AT run: per interval between captures, the pixel's
summed value (from the running averages), and the raw frame at each capture.   pin.py <tag> x,y,lo,hi ..."""
import sys
args = sys.argv[1:]; sys.argv = sys.argv[:1]
exec(open(__file__.replace("pin.py", "score.py")).read().split("def windows")[0])
tag = args[0]; d = os.path.join(C, tag)
fr = {int(l.split()[0]): int(l.split()[1]) for l in open(os.path.join(d, tag + ".frames.txt")) if not l.startswith("first")}
acc, raw = {}, {}
for p in glob.glob(os.path.join(d, "*.exr")):
    n = fr[int(re.search(r"\.(\d+)\.exr$", p).group(1))]
    (acc if ".Accum." in p else raw)[n] = p
for spec in args[1:]:
    x, y, lo, hi = map(int, spec.split(","))
    ns = [n for n in sorted(acc) if lo <= n <= hi]
    A = {n: load(acc[n])[y, x] for n in ns}
    print("pixel (%d,%d), frames %d-%d:" % (x, y, lo, hi))
    for a, b in zip(ns, ns[1:]):
        s = b * A[b] - a * A[a]
        if s > 0.5 or b - a == 1: print("   frames %d-%d: sum %.3f   raw frame %d: %.3f" % (a + 1, b, s, b, load(raw[b])[y, x]))
