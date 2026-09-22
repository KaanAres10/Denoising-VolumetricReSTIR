# Falcor 8.0 vs 9.0 re-baseline: the denoiser table, same metric as m_denoisers.py, two engines.
#
# Every row is the bistro orbit, 300 frames at 1080p, 30 warm-up frames, with the Look tasks' matched
# settings (VR_NRD_SPLIT/SH/TAA/EMISSION/VOLMASK=1, VR_TAA_LDR=1, VR_VOL_NORMAL=gradient), captured by
# Scripts/capture_orbit.py. The 8.0 column comes from the preserved 8.0 binary, re-run with today's
# scripts -- NOT copied from STATE.md, whose table predates later script and guide changes.
#
# The 9.0 column is rb_v9uv_*: 9.0 with every port fix in -- NRDPass no longer re-applies the 8.0-era
# matrix transpose, and VolumeUtils.slang inverts 9.0's new TriangleLightSample.uv so reused emissive
# samples are regenerated at the point that was sampled. Earlier 9.0 runs are kept as the evidence:
#   rb_v9_*               before both fixes (rb_v9_relax / rb_v9_reblur are double-transposed)
#   rb_v9fix_relax/reblur matrix fix only
#   rb_v9_rr              the capture whose clock stalled at file 299; rb_v9_rr_rerun is its clean re-run
#   rb_v9_optix_olddecode 8.0's OptiX normal decode put back, for the OptiX split below
import contextlib
import io

src = open("m_denoisers.py", encoding="utf-8").read().splitlines()
exec("\n".join(src[:22]))  # load() and row() exactly as m_denoisers.py defines them

ROWS = [("raw ReSTIR (+TAA)", "rb_v8_raw", "rb_v9uv_raw"),
        ("OptiX (+guides)", "rb_v8_optix", "rb_v9uv_optix"),
        ("RELAX-SH", "rb_v8_relax", "rb_v9uv_relax"),
        ("REBLUR-SH", "rb_v8_reblur", "rb_v9uv_reblur"),
        ("DLSS Ray Reconstruction", "rb_v8_rr", "rb_v9uv_rr")]
# The same configurations before the lightUV fix, for the brightness comparison below.
BEFORE_UV = {"raw ReSTIR (+TAA)": "rb_v9_raw", "OptiX (+guides)": "rb_v9_optix",
             "RELAX-SH": "rb_v9fix_relax", "REBLUR-SH": "rb_v9fix_reblur",
             "DLSS Ray Reconstruction": "rb_v9_rr_rerun"}


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
#    identical flicker. Before the lightUV fix every configuration rendered ~1% darker on 9.0; after
#    it the mean level matches 8.0. (See VolumeUtils.slang at `outLightUV`.)
print()
print("%-26s %8s %16s %16s" % ("mean level (m_denoisers)", "8.0", "9.0 before fix", "9.0 with fix"))
for label, a, b in ROWS:
    ma = float(np.mean([x.mean() for x in load(a)]))
    m0 = float(np.mean([x.mean() for x in load(BEFORE_UV[label])]))
    mb = float(np.mean([x.mean() for x in load(b)]))
    print("%-26s %8.4f %8.4f %+6.2f%% %8.4f %+6.2f%%"
          % (label, ma, m0, 100 * (m0 / ma - 1), mb, 100 * (mb / ma - 1)))

# 2. OptiX: rb_v9_optix_olddecode is 9.0 with 8.0's `(n - 0.5) * 2` normal decode put back for one
#    run. 8.0 -> olddecode is everything else in the engine, including the dispatch fix that made the
#    normal guide reach OptiX at all; olddecode -> fixed is the decode fix alone. Both 9.0 runs here
#    predate the lightUV fix, so the split is internally consistent but its first row also carries
#    that ~1% darkening (which counts AGAINST OptiX).
print()
va, vo, vb = vals("", "rb_v8_optix"), vals("", "rb_v9_optix_olddecode"), vals("", "rb_v9_optix")
print("%-34s %8s %8s %9s %8s" % ("OptiX", "s=32", "plume", "surfaces", "detail"))
print("%-34s" % "8.0 -> 9.0 with the old decode" + "".join(" %+7.1f%%" % (100 * (y / x - 1)) for x, y in zip(va, vo)))
print("%-34s" % "old decode -> fixed decode" + "".join(" %+7.1f%%" % (100 * (y / x - 1)) for x, y in zip(vo, vb)))
