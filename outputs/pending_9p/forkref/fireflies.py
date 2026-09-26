"""Firefly census of one or more run.sh captures: every 256-frame window's mean, pixels above 1 / 10 by region,
and each window whose largest non-emitter pixel exceeds 10 (where, how big).   fireflies.py <tag> ..."""
import sys
sys.argv, tags = sys.argv[:1], sys.argv[1:]
exec(open(__file__.replace("fireflies.py", "score.py")).read().split("# Reference.")[0])
for tag in tags:
    W = windows(tag); st = np.stack(W); const = st.std(0) < 1e-4 * np.maximum(st.mean(0), 1e-9); del st
    L = [np.where(const | BAD, 0, w) for w in W]
    cnt = lambda t, s: sum(int((w[s] > t).sum()) for w in L)
    print("%-20s %d windows: " % (tag, len(W)) + "  ".join("%s %d/%d" % (r, cnt(1, s), cnt(10, s)) for r, s in REG.items()))
    for k, w in enumerate(L, 1):
        if w.max() > 10:
            y, x = np.unravel_index(w.argmax(), w.shape)
            nb = np.median(w[max(0, y - 3):y + 4, max(0, x - 3):x + 4])
            print("   window %2d: %8.1f at (x %4d, y %4d), neighbourhood median %.4f%s" % (k, w.max(), x, y, nb, "  <- plume core" if 250 <= y < 700 and 900 <= x < 1150 else ""))
