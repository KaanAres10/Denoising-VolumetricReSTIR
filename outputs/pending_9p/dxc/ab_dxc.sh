#!/bin/bash
# Interleaved A/B of the DXC version (1.7 = Falcor 9's packaged one, 1.8 = 1.8.2502.11, the Windows SDK one), per-pass GPU
# ms from Falcor's profiler, 150 frames. The gfx shader cache is wiped before every run (so every run
# compiles; its keys do cover the compiler) and restored at the end.   ab_dxc.sh <rounds> <surface 0|1>
rounds="$1"; surf="$2"
R=/c/research/Denoising-VolumetricReSTIR; B=$R/build/windows-vs2022/bin/Release; D=$R/outputs/pending_9p/dxc; O=$D/ab; mkdir -p $O
cd $R
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
[ -d $B/.shadercache ] && mv $B/.shadercache $B/.shadercache_keep
trap 'rm -rf $B/.shadercache; [ -d $B/.shadercache_keep ] && mv $B/.shadercache_keep $B/.shadercache; cp -p $D/dxc17/* $B/' EXIT
vars=(17 18)
for ((r = 1; r <= rounds; r++)); do
  for ((i = 0; i < 2; i++)); do
    v=${vars[$(( (i + r - 1) % 2 ))]}
    cp -p $D/dxc$v/* $B/; rm -rf $B/.shadercache
    tag="dxc${v}_s${surf}_r$r"
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
print("%-14s GS %6.2f  TR %6.2f  SR %6.2f  FS %6.2f  est %6.2f" % (tag, o.get("Generate Samples", 0), o.get("Temporal Reuse", 0), o.get("Spatial Reuse", 0), o.get("Final Shading", 0), o.get("est", 0)))
PY
  done
done
echo AB_DXC DONE
