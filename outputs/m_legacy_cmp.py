# Falcor 4.x (falcor4-legacy) vs 8.0 vs 9.0: frame cost of the raw estimator alone.
#   legacy_cmp/wall_<legacy|v8|v9>_r<1..3>.txt   "<engine>,n,mean,median,p95,min,max" (+ .csv per frame)
#   legacy_cmp/pass_<engine>*                    per-pass GPU time, one run per engine
# Produced by legacy_cmp/time_batch.ps1 from legacy/Scripts/_time_raw_legacy.py and
# Scripts/time_raw.py, which hold the graph (estimator -> fixed tonemapper), scene, orbit and timing
# identical. Wall clock around renderFrame(): CPU submit + GPU + present, comparable between engines.
import csv
import glob
import json
import os
import statistics as st

D = "legacy_cmp"
ENGINES = [("legacy", "Falcor 4.x"), ("v8", "Falcor 8.0"), ("v9", "Falcor 9.0")]
PASSES = ["Generate Features", "Generate Samples", "Temporal Reuse", "Spatial Reuse", "Copy resource",
          "Final Shading"]


def wall(eng):
    out = []
    for p in sorted(glob.glob(os.path.join(D, "wall_%s_r*.txt" % eng))):
        f = open(p).read().strip().split(",")
        out.append(float(f[2]))
    return out


print("WALL CLOCK per frame, ms (mean of 300 frames per run; 3 runs per engine, order rotated)")
print("%-12s %24s %8s %8s %16s" % ("", "runs", "mean", "median", "vs 4.x (median)"))
base = None
for eng, label in ENGINES:
    w = wall(eng)
    if not w:
        print("%-12s (missing)" % label)
        continue
    md = st.median(w)
    base = base or md
    print("%-12s %24s %8.2f %8.2f %+15.1f%%" % (label, " / ".join("%.1f" % x for x in w), st.mean(w), md,
                                                100 * (md / base - 1)))


def new_passes(eng):
    p = os.path.join(D, "pass_%s.txt.passes.json" % eng)
    if not os.path.exists(p):
        return {}
    out = {}
    for name, v in json.load(open(p)).items():
        if name.endswith("/VolumetricReSTIR/gpu_time"):
            out["(estimator)"] = v["median"]
        elif name.endswith("/gpu_time") and "/VolumetricReSTIR/" in name:
            out[name.split("/")[-2]] = v["median"]
    return out


def legacy_passes():
    # Falcor 4's TimingCapture writes getEventGpuTime / 1000, i.e. SECONDS, one line per frame.
    out = {}
    for n, f in [(n, n.replace(" ", "_")) for n in PASSES] + [("(estimator)", "estimator")]:
        p = os.path.join(D, "pass_legacy_pass_%s.csv" % f)
        if not os.path.exists(p):
            continue
        vals = []
        for row in csv.reader(open(p)):
            for cell in row:
                try:
                    vals.append(float(cell))
                except ValueError:
                    pass
        vals = [v * 1000.0 for v in vals[30:]]  # skip the warm-up frames; seconds -> ms
        if vals:
            out[n] = st.median(vals)
    return out


# CAUTION: Falcor 4's profiler slows Falcor 4 itself (its profiled run: 117.7 ms/frame against 104.6
# unprofiled), while 8.0/9.0's costs ~1 ms. So read the 4.x column by SHARE of the estimator, not by
# absolute ms -- its absolute numbers are inflated by roughly 12%.
per = {"legacy": legacy_passes(), "v8": new_passes("v8"), "v9": new_passes("v9")}
tot = {e: sum(per[e].get(n) or 0 for n in PASSES) for e, _ in ENGINES}
print("\nGPU TIME per pass, ms (median over the run's frames), and share of the passes' sum")
print("%-20s %16s %16s %16s" % ("", "4.x", "8.0", "9.0"))
for n in PASSES + ["(estimator)"]:
    txt = []
    for e, _ in ENGINES:
        c = per[e].get(n)
        if c is None:
            txt.append("-")
        elif n == "(estimator)" or not tot[e]:
            txt.append("%.2f" % c)
        else:
            txt.append("%.2f %5.1f%%" % (c, 100 * c / tot[e]))
    print("%-20s %16s %16s %16s" % ((n,) + tuple(txt)))
