# Is an 8.0 -> 9.0 difference real, or the noise of one random-number stream?
#
# Each engine is rendered with 4 seeds per configuration. There is no seed switch in the renderer, so
# the seed is the warm-up length: the random generator is seeded by the frame counter, which keeps
# counting through the warm-up, so VR_WARM = 30/31/32/33 gives every captured frame different random
# numbers at IDENTICAL camera poses (capture_orbit places the camera by loop index). Bistro's volume
# is a single static frame and the camera is detached from the scene animation, so nothing else moves.
#   seed 30: rb_v8_<cfg>, rb_v9uv_<cfg>      seeds 31-33: sd_<v8|v9uv>_<cfg>_w31..33
#
# Per metric: seed-to-seed spread (sample std as % of the mean) and the change in the mean, with a
# 95% confidence interval from Welch's t (n = 4 per engine). "real" = the interval excludes zero.
import contextlib
import io
import math
import sys

# argv[1] = which 9.0 build: "v9uv" (Slang default FP, before b6628b4) or "v9p" (precise FP, final).
V9 = sys.argv[1] if len(sys.argv) > 1 else "v9uv"

src = open("m_denoisers.py", encoding="utf-8").read().splitlines()
exec("\n".join(src[:22]))  # load() and row() exactly as m_denoisers.py defines them

CFGS = [("raw ReSTIR (+TAA)", "raw"), ("OptiX (+guides)", "optix"), ("RELAX-SH", "relax"),
        ("REBLUR-SH", "reblur"), ("DLSS Ray Reconstruction", "rr")]
METRICS = ["s=32", "plume", "surfaces", "detail"]
T975 = {2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306}


def vals(d):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        row("x", d)
    return [float(x) for x in buf.getvalue().split()[-4:]]


def dirs(eng, cfg):
    return ["rb_%s_%s" % (eng, cfg)] + ["sd_%s_%s_w%d" % (eng, cfg, w) for w in (31, 32, 33)]


def stats(xs):
    n = len(xs)
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / (n - 1)
    return m, v


print("%-24s %-9s %8s %8s %11s %11s %20s  %s" % ("", "metric", "8.0", "9.0", "spread 8.0", "spread 9.0",
                                                 "change [95% CI]", "verdict"), flush=True)
for label, cfg in CFGS:
    a = [vals(d) for d in dirs("v8", cfg)]
    b = [vals(d) for d in dirs(V9, cfg)]
    for j, met in enumerate(METRICS):
        xa, xb = [r[j] for r in a], [r[j] for r in b]
        ma, va = stats(xa)
        mb, vb = stats(xb)
        se = math.sqrt(va / len(xa) + vb / len(xb))
        # Welch-Satterthwaite degrees of freedom
        num = (va / len(xa) + vb / len(xb)) ** 2
        den = (va / len(xa)) ** 2 / (len(xa) - 1) + (vb / len(xb)) ** 2 / (len(xb) - 1)
        df = max(2, min(8, int(round(num / den)) if den > 0 else 8))
        half = T975[df] * se
        d = mb - ma
        lo, hi = 100 * (d - half) / ma, 100 * (d + half) / ma
        verdict = "real" if (lo > 0 or hi < 0) else "noise"
        fmt = "%8.4f" if met == "detail" else "%8.2f"
        print(("%-24s %-9s " + fmt + " " + fmt + " %10.2f%% %10.2f%% %+7.2f%% [%+5.2f,%+5.2f]  %s")
              % (label if j == 0 else "", met, ma, mb, 100 * math.sqrt(va) / ma, 100 * math.sqrt(vb) / mb,
                 100 * d / ma, lo, hi, verdict), flush=True)
