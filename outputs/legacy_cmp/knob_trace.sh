#!/bin/bash
# One volume-only 9.0 frame at orbit pose ~168 deg (frame 310 of a 300-frame orbit, same as
# pose_trace.sh "late"), GPU trace, with extra environment settings. Prints per pass: Mcycles, warp
# instructions executed (millions), registers/thread and active warps.
#   knob_trace.sh <tag> [ENV=VAL ...]
tag="$1"; shift
NG="/c/Program Files/NVIDIA Corporation/Nsight Graphics 2026.2.0/host/windows-desktop-nomad-x64/ngfx.exe"
R=/c/research/Denoising-VolumetricReSTIR
O=$R/outputs/legacy_cmp/knob_trace/$tag; rm -rf "$O"; mkdir -p "$O"
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
B=$R/build/windows-vs2022/bin/Release
# Compile fresh (KEEP_CACHE=1 reuses it): the cache is moved aside for the run and put back afterwards.
# Not needed for a DXC switch -- the cache's keys cover the compiler (pending_9p/dxc/cachekey.sh).
[ "${KEEP_CACHE:-0}" = 1 ] || [ ! -d "$B/.shadercache" ] || mv "$B/.shadercache" "$B/.shadercache_keep"
trap '[ -d "$B/.shadercache_keep" ] && { rm -rf "$B/.shadercache"; mv "$B/.shadercache_keep" "$B/.shadercache"; }' EXIT
ls $B/python310.dll $B/z.dll >/dev/null 2>&1 || (cd $R && ./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target restore_runtime_dlls >/dev/null 2>&1)
(
  for e in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $e; done
  for kv in "$@"; do export "$kv"; done
  cd $R && VR_USE_SURFACE=0 VR_FRAMES=300 VR_ENGINE=v9 timeout 900 "$NG" --activity "GPU Trace Profiler" --set-gpu-clocks ${NG_CLOCKS:-base} \
    --exe "C:\research\Denoising-VolumetricReSTIR\build\windows-vs2022\bin\Release\Mogwai.exe" --dir "C:\research\Denoising-VolumetricReSTIR" \
    --args "--script C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py" \
    --start-after-frames 310 --limit-to-frames 1 --auto-export --output-dir "$(cygpath -m $O)" > "$O/ngfx.log" 2>&1
)
python - "$O/BASE/GPUTRACE_REGIMES.xls" "$tag" <<'PY'
import csv, sys, os
p, tag = sys.argv[1:3]
if not os.path.exists(p): print(tag, "NO TRACE"); sys.exit()
rows = list(csv.reader(open(p, encoding="utf-8", errors="replace"), delimiter="\t"))
d = {r[0].split("/")[-1]: dict(zip(rows[0], r)) for r in rows[1:]}
R = "tpc__sm_rf_registers_allocated_shader_cs_queue_sync_realtime.avg.per_cycle_elapsed"
W = "tpc__warps_active_shader_cs_queue_sync_realtime.avg.per_cycle_elapsed"
C = "gpc__cycles_elapsed.avg"
I = "sm__inst_executed_realtime.avg.pct_of_peak_sustained_elapsed"
T = "l1tex__samp_input_quads_mem_texture_format_3d_realtime.sum"
cells = []
for ps, s in (("Generate Samples", "GS"), ("Temporal Reuse", "TR"), ("Spatial Reuse", "SR"), ("Final Shading", "FS"), ("VolumetricReSTIR", "est")):
    r = d.get(ps)
    if not r: cells.append(s + " -"); continue
    f = lambda k: float(r.get(k) or 0)
    w = f(W); c = f(C)
    cells.append("%s %6.2fMc i%6.0f r%3.0f w%5.2f" % (s, c / 1e6, f(I) * c / 1e8, f(R) / w / 32 if w else 0, w))
print("%-12s " % tag + " | ".join(cells) + "  tex3d %.1fM" % (float(d.get("VolumetricReSTIR", {}).get(T) or 0) / 1e6))
PY
