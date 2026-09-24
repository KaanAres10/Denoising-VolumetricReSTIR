#!/bin/bash
# Volume-only GPU trace of one frame at a chosen point of the orbit, legacy fork and 9.0, plain (no
# shader profiler). VR_FRAMES=PT_FRAMES (default 300): frame F of the process is orbit step ~F-31 (30 warm-up frames).
# Legacy swaps in better-optimized kernels ~60 frames in, so trace it later than that.
#   pose_trace.sh <tag> <start-after-frames> [legacy|v9|both]
tag="$1"; start="$2"; which="${3:-both}"
NG="/c/Program Files/NVIDIA Corporation/Nsight Graphics 2026.2.0/host/windows-desktop-nomad-x64/ngfx.exe"
R=/c/research/Denoising-VolumetricReSTIR
O=$R/outputs/legacy_cmp/pose_trace
for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai still running, abort"; exit 1; }
trace() { # $1 engine
  local d="$O/${tag}_$1"; rm -rf "$d"; mkdir -p "$d"
  local W="C:/research/Denoising-VolumetricReSTIR/outputs/legacy_cmp/pose_trace/${tag}_$1"
  if [ "$1" = legacy ]; then
    (cd $R/legacy && VR_NO_SURFACE=1 VR_FRAMES=${PT_FRAMES:-300} timeout 900 "$NG" --activity "GPU Trace Profiler" \
      --exe "C:\research\Denoising-VolumetricReSTIR\legacy\Bin\x64\Release\Mogwai.exe" --dir "C:\research\Denoising-VolumetricReSTIR\legacy" \
      --args "--script C:\research\Denoising-VolumetricReSTIR\legacy\Scripts\_time_raw_legacy.py" \
      --start-after-frames $start --limit-to-frames 1 --auto-export --output-dir "$W" > "$d/ngfx.log" 2>&1)
  else
    (cd $R && VR_USE_SURFACE=0 VR_FRAMES=${PT_FRAMES:-300} VR_ENGINE=v9 timeout 900 "$NG" --activity "GPU Trace Profiler" \
      --exe "C:\research\Denoising-VolumetricReSTIR\build\windows-vs2022\bin\Release\Mogwai.exe" --dir "C:\research\Denoising-VolumetricReSTIR" \
      --args "--script C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py" \
      --start-after-frames $start --limit-to-frames 1 --auto-export --output-dir "$W" > "$d/ngfx.log" 2>&1)
  fi
}
[ "$which" != v9 ] && trace legacy
[ "$which" != legacy ] && trace v9
python - "$O" "$tag" <<'PY'
import csv, sys, os
O, tag = sys.argv[1:3]
K = {"Mcyc": ("gpc__cycles_elapsed.avg", 1e6),
     "tex3d": ("l1tex__samp_input_quads_mem_texture_format_3d_realtime.sum", 1e6),
     "thr": ("Top_Level_Triage.tpc__threads_launched_shader_cs_and_vtg_realtime.sum", 1e6)}
R = "tpc__sm_rf_registers_allocated_shader_cs_queue_sync_realtime.avg.per_cycle_elapsed"
W = "tpc__warps_active_shader_cs_queue_sync_realtime.avg.per_cycle_elapsed"
for eng in ("legacy", "v9"):
    p = os.path.join(O, "%s_%s" % (tag, eng), "BASE", "GPUTRACE_REGIMES.xls")
    if not os.path.exists(p): continue
    rows = list(csv.reader(open(p, encoding="utf-8", errors="replace"), delimiter="\t"))
    d = {r[0].split("/")[-1]: dict(zip(rows[0], r)) for r in rows[1:]}
    for ps, s in (("Generate Samples", "GS"), ("Temporal Reuse", "TR"), ("Spatial Reuse", "SR"), ("Final Shading", "FS"), ("VolumetricReSTIR", "est")):
        r = d.get(ps)
        if not r: print("%-8s %-6s %s -" % (tag, eng, s)); continue
        f = lambda k: float(r.get(k) or 0)
        w = f(W)
        print("%-8s %-6s %-3s regs %3.0f warps %5.2f  " % (tag, eng, s, f(R) / w / 32 if w else 0, w)
              + "  ".join("%s %7.2f" % (n, f(k) / sc) for n, (k, sc) in K.items()))
PY
