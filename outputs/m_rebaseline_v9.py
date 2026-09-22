# Falcor 8.0 vs 9.0 re-baseline: the denoiser table, same metric as m_denoisers.py, two engines.
#
# Every row is the bistro orbit, 300 frames at 1080p, 30 warm-up frames, with the Look tasks' matched
# settings (VR_NRD_SPLIT/SH/TAA/EMISSION/VOLMASK=1, VR_TAA_LDR=1, VR_VOL_NORMAL=gradient), captured by
# Scripts/capture_orbit.py. The 8.0 column comes from the preserved 8.0 binary, re-run with today's
# scripts -- NOT copied from STATE.md, whose table predates later script and guide changes.
#
# The 9.0 NRD rows are rb_v9fix_*: after NRDPass stopped re-applying the 8.0-era matrix transpose
# (rb_v9_relax / rb_v9_reblur are the double-transposed runs, kept for the A/B). The 9.0 RR row is
# rb_v9_rr_rerun: rb_v9_rr hit a clock stall at file 299 and is kept only as the example of one.
import contextlib
import io

src = open("m_denoisers.py", encoding="utf-8").read().splitlines()
exec("\n".join(src[:22]))  # load() and row() exactly as m_denoisers.py defines them

ROWS = [("raw ReSTIR (+TAA)", "rb_v8_raw", "rb_v9_raw"),
        ("OptiX (+guides)", "rb_v8_optix", "rb_v9_optix"),
        ("RELAX-SH", "rb_v8_relax", "rb_v9fix_relax"),
        ("REBLUR-SH", "rb_v8_reblur", "rb_v9fix_reblur"),
        ("DLSS Ray Reconstruction", "rb_v8_rr", "rb_v9_rr_rerun")]


def vals(label, d):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        row(label, d)
    return [float(x) for x in buf.getvalue().split()[-4:]]


print("%-26s %20s %20s %20s %20s" % ("", "s=32", "plume", "surfaces", "detail"))
print("%-26s" % "" + "  8.0    9.0     d%  " * 4)
for label, a, b in ROWS:
    va, vb = vals(label, a), vals(label, b)
    cells = []
    for i, (x, y) in enumerate(zip(va, vb)):
        fmt = " %6.2f %6.2f %+6.1f%% " if i < 3 else " %.4f %.4f %+5.1f%% "
        cells.append(fmt % (x, y, 100 * (y / x - 1)))
    print("%-26s" % label + "".join(cells))

# --- Why the numbers move (see STATE.md, "Falcor 9.0 port") -----------------------------------------
#
# 1. Brightness. The metric divides by the capture's mean level, so a darker image scores worse at
#    identical flicker. A mean-level drop of b% alone reads as roughly +b% on every column.
print()
print("%-26s %8s %8s %10s" % ("mean level (m_denoisers)", "8.0", "9.0", "change"))
for label, a, b in ROWS:
    ma = float(np.mean([x.mean() for x in load(a)]))
    mb = float(np.mean([x.mean() for x in load(b)]))
    print("%-26s %8.4f %8.4f %+9.2f%%" % (label, ma, mb, 100 * (mb / ma - 1)))

# 2. OptiX: rb_v9_optix_olddecode is 9.0 with 8.0's `(n - 0.5) * 2` normal decode put back for one
#    run. 8.0 -> olddecode is everything else in the engine, including the dispatch fix that made the
#    normal guide reach OptiX at all; olddecode -> fixed is the decode fix alone.
print()
va, vo, vb = vals("", "rb_v8_optix"), vals("", "rb_v9_optix_olddecode"), vals("", "rb_v9_optix")
print("%-34s %8s %8s %9s %8s" % ("OptiX", "s=32", "plume", "surfaces", "detail"))
print("%-34s" % "8.0 -> 9.0 with the old decode" + "".join(" %+7.1f%%" % (100 * (y / x - 1)) for x, y in zip(va, vo)))
print("%-34s" % "old decode -> fixed decode" + "".join(" %+7.1f%%" % (100 * (y / x - 1)) for x, y in zip(vo, vb)))
