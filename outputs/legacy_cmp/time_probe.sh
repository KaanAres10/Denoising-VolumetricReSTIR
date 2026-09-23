#!/bin/bash
# Timing probe: apply one regex edit to a DEPLOYED 9.0 shader, run time_raw.py (full scene unless
# PROBE_SURFACE=0) with Falcor's profiler, print per-pass GPU ms, restore the shader.
#   time_probe.sh <tag> <shader path under bin/Release/shaders> <python regex> <replacement>
tag="$1"; rel="$2"; pat="$3"; rep="$4"
R=/c/research/Denoising-VolumetricReSTIR
SH="$R/build/windows-vs2022/bin/Release/shaders/$rel"
OUT="$R/outputs/legacy_cmp/tprobe/$tag"; rm -rf "$OUT"; mkdir -p "$OUT"
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
VR_USE_SURFACE=${PROBE_SURFACE:-1} VR_PASS_TIMES=1 VR_FRAMES=150 VR_ENGINE=v9 VR_RESULT="C:/research/Denoising-VolumetricReSTIR/outputs/legacy_cmp/tprobe/$tag/r.txt" timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py" > "$OUT/run.log" 2>&1
cp -p "$OUT/orig.slang" "$SH"; cmp -s "$OUT/orig.slang" "$SH" && echo "restored $rel"
python - "$OUT" "$tag" <<'PY'
import json, sys, os
out, tag = sys.argv[1:3]
p = os.path.join(out, "r.txt.passes.json")
if not os.path.exists(p): print(tag, "FAILED"); sys.exit()
o = {}
for k, v in json.load(open(p)).items():
    if k.endswith("/VolumetricReSTIR/gpu_time"): o["est"] = v["median"]
    elif k.endswith("/gpu_time") and "/VolumetricReSTIR/" in k: o[k.split("/")[-2]] = v["median"]
print("%-16s GS %6.2f  TR %6.2f  SR %6.2f  FS %6.2f  est %6.2f" % (tag, o.get("Generate Samples", 0), o.get("Temporal Reuse", 0), o.get("Spatial Reuse", 0), o.get("Final Shading", 0), o.get("est", 0)))
PY
