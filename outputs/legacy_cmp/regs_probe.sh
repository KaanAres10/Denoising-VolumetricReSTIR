#!/bin/bash
# Register probe: apply one regex edit to a DEPLOYED 9.0 shader, GPU-trace one volume-only frame,
# print registers/thread, active warps and Mcycles per estimator pass, then restore the shader.
#   regs_probe.sh <tag> <shader path under bin/Release/shaders> <python regex> <replacement>
# With an empty regex it traces the unmodified build (the baseline).
tag="$1"; rel="$2"; pat="$3"; rep="$4"
R=/c/research/Denoising-VolumetricReSTIR
SH="$R/build/windows-vs2022/bin/Release/shaders/$rel"
NG="/c/Program Files/NVIDIA Corporation/Nsight Graphics 2026.2.0/host/windows-desktop-nomad-x64/ngfx.exe"
OUTW="C:/research/Denoising-VolumetricReSTIR/outputs/legacy_cmp/regs/$tag"
OUT="$R/outputs/legacy_cmp/regs/$tag"
rm -rf "$OUT"; mkdir -p "$OUT"
cp -p "$SH" "$OUT/orig.slang"
if [ -n "$pat" ]; then
  python - "$SH" "$pat" "$rep" <<'PY' || { cp -p "$OUT/orig.slang" "$SH"; exit 1; }
import re, sys
p, pat, rep = sys.argv[1:4]
s = open(p, encoding="utf-8").read()
s2, n = re.subn(pat, rep, s, flags=re.S)
if n == 0: sys.exit("pattern did not match")
open(p, "w", encoding="utf-8", newline="").write(s2); print("edit applied x%d" % n)
PY
fi
cd "$R"
for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
ls build/windows-vs2022/bin/Release/libprotoc.dll build/windows-vs2022/bin/Release/z.dll >/dev/null 2>&1 || ./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target restore_runtime_dlls >/dev/null 2>&1
VR_USE_SURFACE=${PROBE_SURFACE:-0} VR_FRAMES=80 VR_ENGINE=v9 timeout 900 "$NG" --activity "GPU Trace Profiler" --exe "$R/build/windows-vs2022/bin/Release/Mogwai.exe" --dir "C:\research\Denoising-VolumetricReSTIR" --args "--script C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py" --start-after-frames 60 --limit-to-frames 1 ${PROBE_NGFX_EXTRA} --auto-export --output-dir "$OUTW" > "$OUT/ngfx.log" 2>&1
cp -p "$OUT/orig.slang" "$SH"
cmp -s "$OUT/orig.slang" "$SH" && echo "restored $rel"
python - "$OUT" "$tag" <<'PY'
import csv, sys, os
out, tag = sys.argv[1:3]
p = os.path.join(out, "BASE", "GPUTRACE_REGIMES.xls")
if not os.path.exists(p): print(tag, "NO TRACE"); sys.exit()
rows = list(csv.reader(open(p, encoding="utf-8", errors="replace"), delimiter="\t"))
d = {r[0].split("/")[-1]: dict(zip(rows[0], r)) for r in rows[1:]}
R = "tpc__sm_rf_registers_allocated_shader_cs_queue_sync_realtime.avg.per_cycle_elapsed"
W = "tpc__warps_active_shader_cs_queue_sync_realtime.avg.per_cycle_elapsed"
C = "gpc__cycles_elapsed.avg"
cells = []
for ps, short in (("Generate Samples", "GS"), ("Spatial Reuse", "SR"), ("Temporal Reuse", "TR"), ("Final Shading", "FS")):
    r = d.get(ps)
    if not r: cells.append("%s -" % short); continue
    w = float(r[W]); rg = float(r[R]); c = float(r[C])
    cells.append("%s %3.0f regs %5.2f warps %5.2f Mcyc" % (short, rg / w / 32 if w else 0, w, c / 1e6))
print("%-18s " % tag + " | ".join(cells))
PY
