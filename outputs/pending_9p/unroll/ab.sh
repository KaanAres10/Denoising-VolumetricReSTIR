#!/bin/bash
# Interleaved A/B of the unrolled per-sample loops (VolumeTrackingAdapterGVDB.slang): HEAD's deployed
# shader ("old") against the working tree's ("new"), per-pass GPU ms (median of 150 frames).
#   ab.sh <rounds> <surface 0|1>
rounds="$1"; surf="$2"
R=/c/research/Denoising-VolumetricReSTIR; B=$R/build/windows-vs2022/bin/Release
S=$B/shaders/RenderPasses/VolumetricReSTIR; F=VolumeTrackingAdapterGVDB.slang
D=$R/outputs/pending_9p/unroll; O=$D/ab; mkdir -p $O
cd $R
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
ls $B/python310.dll $B/z.dll >/dev/null 2>&1 || ./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target restore_runtime_dlls >/dev/null 2>&1
git show HEAD:Source/RenderPasses/VolumetricReSTIR/$F > $D/old.slang
cp -p Source/RenderPasses/VolumetricReSTIR/$F $D/new.slang
trap 'cp -p $D/new.slang $S/$F' EXIT
vars=(old new)
for ((r = 1; r <= rounds; r++)); do
  for ((i = 0; i < 2; i++)); do
    v=${vars[$(( (i + r - 1) % 2 ))]}
    cp $D/$v.slang $S/$F
    tag="${v}_s${surf}_r$r"
    ( for e in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $e; done
      VR_USE_SURFACE=$surf VR_PASS_TIMES=1 VR_FRAMES=150 VR_ENGINE=v9 VR_RESULT="$(cygpath -m $O)/$tag.txt" \
        timeout 900 $B/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py" > $O/$tag.log 2>&1 )
    python - "$O/$tag.txt.passes.json" "$tag" <<'PY'
import json, sys, os
p, tag = sys.argv[1:3]
if not os.path.exists(p): print(tag, "FAILED"); sys.exit()
o = {}
for k, v in json.load(open(p)).items():
    if k.endswith("/VolumetricReSTIR/gpu_time"): o["est"] = v["median"]
    elif k.endswith("/gpu_time") and "/VolumetricReSTIR/" in k: o[k.split("/")[-2]] = v["median"]
print("%-12s GS %6.2f  TR %6.2f  SR %6.2f  FS %6.2f  est %6.2f" % (tag, o.get("Generate Samples", 0), o.get("Temporal Reuse", 0), o.get("Spatial Reuse", 0), o.get("Final Shading", 0), o.get("est", 0)))
PY
  done
done
echo "AB DONE"
