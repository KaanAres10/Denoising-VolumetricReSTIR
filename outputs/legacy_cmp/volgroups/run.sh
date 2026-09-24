#!/bin/bash
# Volume-only 9.0: thread-group layout A/B, interleaved (order rotated per round), per-pass GPU ms.
R=/c/research/Denoising-VolumetricReSTIR
O=$R/outputs/legacy_cmp/volgroups
cd "$R"
for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
run() { # $1 group $2 tag
  VR_GROUP=$1 VR_USE_SURFACE=0 VR_PASS_TIMES=1 VR_FRAMES=150 VR_ENGINE=v9 VR_RESULT="C:/research/Denoising-VolumetricReSTIR/outputs/legacy_cmp/volgroups/$2.txt" \
    timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py" > "$O/$2.log" 2>&1
  python - "$O/$2.txt.passes.json" "$2" <<'PY'
import json, sys, os
p, tag = sys.argv[1:3]
if not os.path.exists(p): print(tag, "FAILED"); sys.exit()
o = {}
for k, v in json.load(open(p)).items():
    if k.endswith("/VolumetricReSTIR/gpu_time"): o["est"] = v["median"]
    elif k.endswith("/gpu_time") and "/VolumetricReSTIR/" in k: o[k.split("/")[-2]] = v["median"]
print("%-12s GS %6.2f  TR %6.2f  SR %6.2f  FS %6.2f  est %6.2f" % (tag, o.get("Generate Samples", 0), o.get("Temporal Reuse", 0), o.get("Spatial Reuse", 0), o.get("Final Shading", 0), o.get("est", 0)))
PY
}
orders=("8x8 16x16 16x8 8x16" "16x16 16x8 8x16 8x8" "16x8 8x16 8x8 16x16")
r=1
for ord in "${orders[@]}"; do for g in $ord; do run $g "g${g}_r$r"; done; r=$((r+1)); done
echo VOLGROUPS DONE
