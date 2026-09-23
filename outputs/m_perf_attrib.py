# Attribute 9.0's estimator slowdown by switching paths off. Per-pass GPU medians (Falcor profiler),
# raw ReSTIR (no denoiser), bistro orbit unless noted; perfx_* averaged over 2 interleaved reps.
#   full   : perfpass_<eng>_raw          everything on
#   vol    : perfx_<eng>_vol_r*          VR_USE_SURFACE=0  -- GVDB volume path only
#   noemis : perfx_<eng>_noemis_r*       VR_USE_EMISSIVE=0 -- surfaces, no emissive-light evaluation
#   plume  : perfx_<eng>_plume_r*        plume scene, camera held -- volume + env light + ground plane
import glob
import json
import os
import statistics as st

STAGES = ["VolumetricReSTIR", "Spatial Reuse", "Generate Samples", "Temporal Reuse", "Final Shading",
          "EmissivePowerSampler::update", "Generate Features"]


def lanes(path):
    if not os.path.exists(path):
        return None
    out = {}
    for k, v in json.load(open(path))["lanes"].items():
        if k.endswith("/gpu_time"):
            out[k[:-len("/gpu_time")].rsplit("/", 1)[-1] if "/VolumetricReSTIR/" in k else k[:-len("/gpu_time")].rsplit("/", 1)[-1]] = v["median"]
    return out


def avg(paths):
    ls = [l for l in (lanes(p) for p in paths) if l]
    if not ls:
        return None
    keys = set().union(*ls)
    return {k: st.mean([l.get(k, 0.0) for l in ls]) for k in keys}


def runs(eng, case):
    if case == "full":
        return [os.path.join("perfpass_%s_raw" % eng, "raw_pass_times.json")]
    return sorted(glob.glob(os.path.join("perfx_%s_%s_r*" % (eng, case), "%s_pass_times.json" % case)))


print("GPU ms per frame (median), 8.0 -> 9.0")
print("%-30s" % "" + "".join("%26s" % c for c in ("full bistro", "volume only", "no emissive", "plume scene")))
data = {c: (avg(runs("v8", c)), avg(runs("v9", c))) for c in ("full", "vol", "noemis", "plume")}
for s in STAGES:
    cells = []
    for c in ("full", "vol", "noemis", "plume"):
        a, b = data[c]
        if not a or not b or (a.get(s, 0) < 0.05 and b.get(s, 0) < 0.05):
            cells.append("%26s" % "-")
            continue
        x, y = a.get(s, 0.0), b.get(s, 0.0)
        cells.append("%9.2f -> %6.2f %+6.0f%%" % (x, y, 100 * (y / x - 1) if x > 0 else float("nan")))
    print("%-30s" % s + "".join(cells))
