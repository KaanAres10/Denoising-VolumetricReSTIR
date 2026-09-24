#!/bin/bash
# Interleaved A/B of deployed shader variants, volume-only (and optionally full scene), per-pass GPU ms.
#   ab.sh <variants dir> <rounds> <surface 0|1> <variant> [<variant> ...]
# Each variant is a subdirectory holding replacement files for shaders/RenderPasses/VolumetricReSTIR.
# Order rotates every round. HEAD's files (variant A) are restored at the end.
V="$1"; rounds="$2"; surf="$3"; shift 3; vars=("$@")
R=/c/research/Denoising-VolumetricReSTIR; B=$R/build/windows-vs2022/bin/Release; S=$B/shaders/RenderPasses/VolumetricReSTIR
cd $R
for e in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $e; done
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
ls $B/libprotoc.dll $B/z.dll >/dev/null 2>&1 || ./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target restore_runtime_dlls >/dev/null 2>&1
n=${#vars[@]}
for ((r = 1; r <= rounds; r++)); do
  for ((i = 0; i < n; i++)); do
    v=${vars[$(( (i + r - 1) % n ))]}
    cp $V/$v/* $S/
    tag="${v}_s${surf}_r$r"
    VR_USE_SURFACE=$surf VR_PASS_TIMES=1 VR_FRAMES=150 VR_ENGINE=v9 VR_RESULT="C:/research/Denoising-VolumetricReSTIR/${V#$R/}/$tag.txt" \
      timeout 900 $B/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py" > $V/$tag.log 2>&1
    python - "$V/$tag.txt.passes.json" "$tag" <<'PY'
import json, sys, os
p, tag = sys.argv[1:3]
if not os.path.exists(p): print(tag, "FAILED"); sys.exit()
o = {}
for k, v in json.load(open(p)).items():
    if k.endswith("/VolumetricReSTIR/gpu_time"): o["est"] = v["median"]
    elif k.endswith("/gpu_time") and "/VolumetricReSTIR/" in k: o[k.split("/")[-2]] = v["median"]
print("%-14s GS %6.2f  TR %6.2f  SR %6.2f  FS %6.2f  est %6.2f" % (tag, o.get("Generate Samples", 0), o.get("Temporal Reuse", 0), o.get("Spatial Reuse", 0), o.get("Final Shading", 0), o.get("est", 0)))
PY
  done
done
cp $V/A/* $S/
echo "AB DONE (deployed = A)"
