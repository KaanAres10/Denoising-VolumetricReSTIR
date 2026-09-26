import csv, sys
rows = list(csv.reader(open(sys.argv[1] + "/BASE/GPUTRACE_REGIMES.xls", encoding="utf-8", errors="replace"), delimiter="\t"))
d = {r[0].split("/")[-1]: dict(zip(rows[0], r)) for r in rows[1:]}
R = "tpc__sm_rf_registers_allocated_shader_cs_queue_sync_realtime.avg.per_cycle_elapsed"; W = "tpc__warps_active_shader_cs_queue_sync_realtime.avg.per_cycle_elapsed"
r = d.get("Generate Features", {}); f = lambda k: float(r.get(k) or 0)
print(sys.argv[2], "GF %.2f Mcyc regs %.0f warps %.1f | est %.2f" % (f("gpc__cycles_elapsed.avg") / 1e6, f(R) / max(f(W), 1e-9) / 32, f(W), float(d["VolumetricReSTIR"]["gpc__cycles_elapsed.avg"]) / 1e6))
