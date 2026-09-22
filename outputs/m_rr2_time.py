# Cost of RR2 vs previous Ray Reconstruction: per-pass GPU time from Falcor's profiler (VR_PASS_TIMES=1)
# and end-to-end wall clock, bistro orbit at 1080p DLAA, 300 frames, runs interleaved.
import csv, glob, json, os, re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = "/onFrameRender/RenderGraphExe::execute()/DLSSDPass/gpu_time"
CPU = "/onFrameRender/RenderGraphExe::execute()/DLSSDPass/cpu_time"
LABEL = {"t_prev_E": "310.7.0 E", "t_cur_E": "310.9.1 E", "t_cur_F": "310.9.1 F (RR2)"}

groups = defaultdict(list)
for js in sorted(glob.glob(os.path.join(HERE, "t_*", "*_pass_times.json"))):
    tag = os.path.basename(js)[: -len("_pass_times.json")]
    lanes = json.load(open(js))["lanes"]
    with open(os.path.join(os.path.dirname(js), tag + "_frame_times.csv")) as fh:
        ms = [float(r["ms"]) for r in csv.DictReader(fh)]
    groups[re.sub(r"_r\d+$", "", tag)].append(
        (tag, lanes[LANE]["median"], lanes[LANE]["mean"], lanes[CPU]["median"], sum(ms) / len(ms)))

print("%-18s %-12s %14s %12s %14s %12s" % ("config", "run", "RR gpu median", "RR gpu mean", "RR cpu median", "frame mean"))
for key in ("t_prev_E", "t_cur_E", "t_cur_F"):
    for tag, gmed, gmean, cmed, frame in groups.get(key, []):
        print("%-18s %-12s %11.3f ms %9.3f ms %11.3f ms %9.2f ms" % (LABEL[key], tag[-2:], gmed, gmean, cmed, frame))
