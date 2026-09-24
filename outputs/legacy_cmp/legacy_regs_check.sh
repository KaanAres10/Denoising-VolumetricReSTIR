#!/bin/bash
# Does the Falcor 4.x fork compile the same kernels every run? Volume-only GPU traces of the legacy
# build, alternating plain / with the real-time shader profiler, same command otherwise.
# Prints registers per thread, warps, Mcycles per estimator pass from each trace's regimes.
NG="/c/Program Files/NVIDIA Corporation/Nsight Graphics 2026.2.0/host/windows-desktop-nomad-x64/ngfx.exe"
R=/c/research/Denoising-VolumetricReSTIR
O=$R/outputs/legacy_cmp/legacy_regs_check
for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
one() { # $1 tag  $2 extra ngfx args
  rm -rf "$O/$1"; mkdir -p "$O/$1"
  (cd $R/legacy && VR_NO_SURFACE=1 VR_FRAMES=80 timeout 900 "$NG" --activity "GPU Trace Profiler" \
    --exe "C:\research\Denoising-VolumetricReSTIR\legacy\Bin\x64\Release\Mogwai.exe" \
    --dir "C:\research\Denoising-VolumetricReSTIR\legacy" \
    --args "--script C:\research\Denoising-VolumetricReSTIR\legacy\Scripts\_time_raw_legacy.py" \
    --start-after-frames 60 --limit-to-frames 1 $2 --auto-export \
    --output-dir "C:/research/Denoising-VolumetricReSTIR/outputs/legacy_cmp/legacy_regs_check/$1" > "$O/$1/ngfx.log" 2>&1)
  python - "$O/$1/BASE/GPUTRACE_REGIMES.xls" "$1" <<'PY'
import csv, sys, os
p, tag = sys.argv[1:3]
if not os.path.exists(p): print(tag, "NO TRACE"); sys.exit()
rows = list(csv.reader(open(p, encoding="utf-8", errors="replace"), delimiter="\t"))
d = {r[0].split("/")[-1]: dict(zip(rows[0], r)) for r in rows[1:]}
R = "tpc__sm_rf_registers_allocated_shader_cs_queue_sync_realtime.avg.per_cycle_elapsed"
W = "tpc__warps_active_shader_cs_queue_sync_realtime.avg.per_cycle_elapsed"
C = "gpc__cycles_elapsed.avg"
cells = []
for ps, s in (("Generate Samples", "GS"), ("Temporal Reuse", "TR"), ("Spatial Reuse", "SR"), ("Final Shading", "FS"), ("VolumetricReSTIR", "est")):
    r = d.get(ps)
    if not r: cells.append(s + " -"); continue
    w = float(r.get(W) or 0); rg = float(r.get(R) or 0); c = float(r.get(C) or 0)
    cells.append("%s %3.0f/%5.2f %6.2f" % (s, rg / w / 32 if w else 0, w, c / 1e6))
print("%-10s regs/warps Mcyc: " % tag + " | ".join(cells))
PY
}
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai still running, abort"; exit 1; }
one plain1 ""
one prof1 "--real-time-shader-profiler"
one plain2 ""
one prof2 "--real-time-shader-profiler"
echo LEGACY REGS CHECK DONE
