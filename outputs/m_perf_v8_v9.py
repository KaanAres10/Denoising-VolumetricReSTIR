# Frame cost, Falcor 8.0 vs 9.0: bistro orbit, 1080p, 300 frames, the matched configuration.
#   perf_<v8|v9>_<cfg>_r<1|2>/<cfg>_frame_times.csv   wall clock per frame (VR_TIME=1), 2 interleaved reps
#   perfpass_<v8|v9>_<cfg>/<cfg>_pass_times.json      Falcor profiler, per-pass GPU time (VR_PASS_TIMES=1)
# Wall clock is CPU submit + GPU + present -- an upper bound, but directly comparable between engines.
# The rep-to-rep spread is printed next to each engine so a small difference can be judged against it.
import csv
import json
import os
import statistics as st
import sys

# argv[1] = directory prefix: "perf" (first measurement, 9.0 with Slang's default FP) or
# "perf2" (after the precise-FP fix, 8.0 re-run in the same session).
PFX = sys.argv[1] if len(sys.argv) > 1 else "perf"

CFGS = [("raw ReSTIR (+TAA)", "raw"), ("OptiX (+guides)", "optix"), ("RELAX-SH", "relax"),
        ("REBLUR-SH", "reblur"), ("DLSS Ray Reconstruction", "rr")]


def frame_ms(eng, cfg, rep):
    p = os.path.join("%s_%s_%s_r%d" % (PFX, eng, cfg, rep), "%s_frame_times.csv" % cfg)
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        return [float(r["ms"]) for r in csv.DictReader(fh)]


print("WALL CLOCK per frame (ms), mean over 300 frames; [rep1, rep2]")
print("%-24s %22s %22s %9s %9s" % ("", "8.0", "9.0", "median", "change"))
for label, cfg in CFGS:
    out = {}
    for eng in ("v8", "v9"):
        reps = [frame_ms(eng, cfg, r) for r in (1, 2)]
        reps = [r for r in reps if r]
        out[eng] = (reps, [st.mean(r) for r in reps], [st.median(r) for r in reps])
    if not out["v8"][0] or not out["v9"][0]:
        print("%-24s (missing)" % label)
        continue
    m8, m9 = st.mean(out["v8"][1]), st.mean(out["v9"][1])
    d8, d9 = st.mean(out["v8"][2]), st.mean(out["v9"][2])
    print("%-24s %7.2f [%s] %7.2f [%s] %4.1f->%-4.1f %+7.1f%%"
          % (label, m8, ", ".join("%.1f" % x for x in out["v8"][1]), m9, ", ".join("%.1f" % x for x in out["v9"][1]),
             d8, d9, 100 * (m9 / m8 - 1)))


def lanes(eng, cfg):
    p = os.path.join("%s_%s_%s" % (PFX.replace("perf", "perfpass"), eng, cfg), "%s_pass_times.json" % cfg)
    if not os.path.exists(p):
        return {}
    return {k: v for k, v in json.load(open(p))["lanes"].items() if k.endswith("/gpu_time")}


print("\nGPU TIME per pass (ms, median over the capture), passes over 0.3 ms on either engine")
for label, cfg in CFGS:
    a, b = lanes("v8", cfg), lanes("v9", cfg)
    if not a or not b:
        print("\n%s: (missing)" % label)
        continue
    print("\n%s" % label)
    names = sorted(set(a) | set(b), key=lambda k: -max(a.get(k, {}).get("median", 0), b.get(k, {}).get("median", 0)))
    for k in names:
        x, y = a.get(k, {}).get("median"), b.get(k, {}).get("median")
        if max(x or 0, y or 0) < 0.3:
            continue
        short = k.replace("/gpu_time", "")
        short = short if len(short) <= 58 else "..." + short[-55:]
        if x and y:
            print("  %-58s %8.2f %8.2f %+7.1f%%" % (short, x, y, 100 * (y / x - 1)))
        else:
            print("  %-58s %8s %8s   (only on %s)" % (short, "%.2f" % x if x else "-", "%.2f" % y if y else "-",
                                                     "8.0" if x else "9.0"))
