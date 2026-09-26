"""Per-pass GPU time (ms), registers and warps from a GPU Trace export: tsum.py <trace dir> <tag>"""
import csv, sys, os
tag = sys.argv[2]
p = next((os.path.join(sys.argv[1], b, "GPUTRACE_REGIMES.xls") for b in ("BASE", "BASE_UNLOCKED") if os.path.exists(os.path.join(sys.argv[1], b, "GPUTRACE_REGIMES.xls"))), "")
if not os.path.exists(p): print(tag, "NO TRACE"); sys.exit()
rows = list(csv.reader(open(p, encoding="utf-8", errors="replace"), delimiter="\t"))
d = {r[0].split("/")[-1]: dict(zip(rows[0], r)) for r in rows[1:]}
R = "tpc__sm_rf_registers_allocated_shader_cs_queue_sync_realtime.avg.per_cycle_elapsed"
W = "tpc__warps_active_shader_cs_queue_sync_realtime.avg.per_cycle_elapsed"
cells = []
for ps, s in (("Generate Samples", "GS"), ("Temporal Reuse", "TR"), ("Spatial Reuse", "SR"), ("Final Shading", "FS"), ("VolumetricReSTIR", "est"), ("onFrameRender", "frame")):
    r = d.get(ps)
    if not r: cells.append(s + " -"); continue
    f = lambda k: float(r.get(k) or 0)
    rate = f("gpc__cycles_elapsed.avg.per_second"); rate = rate * 1e6 if rate < 1e5 else rate
    ms = f("gpc__cycles_elapsed.avg") / max(rate, 1) * 1e3
    w = f(W)
    cells.append("%s %5.2fms r%3.0f w%4.1f" % (s, ms, f(R) / w / 32 if w else 0, w) if s not in ("est", "frame") else "%s %5.2fms" % (s, ms))
clk = float(d.get("onFrameRender", {}).get("gpc__cycles_elapsed.avg.per_second") or 0); clk = clk if clk < 1e5 else clk / 1e6
print("%-14s " % tag + " | ".join(cells) + "  gpc %.0f MHz" % clk)
