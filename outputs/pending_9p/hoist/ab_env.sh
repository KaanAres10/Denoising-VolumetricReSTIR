#!/bin/bash
# Interleaved A/B over environment settings, per-pass GPU ms (median of 150 frames).
#   ab_env.sh <out dir> <rounds> <spec> [<spec> ...]     spec = tag:surface:ENV=VAL,ENV=VAL (env may be empty)
O="$1"; rounds="$2"; shift 2; specs=("$@")
R=/c/research/Denoising-VolumetricReSTIR; B=$R/build/windows-vs2022/bin/Release
cd $R; mkdir -p $O
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
ls $B/libprotoc.dll $B/z.dll >/dev/null 2>&1 || ./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target restore_runtime_dlls >/dev/null 2>&1
n=${#specs[@]}
for ((r = 1; r <= rounds; r++)); do
  for ((i = 0; i < n; i++)); do
    spec=${specs[$(( (i + r - 1) % n ))]}
    IFS=: read -r tag surf envs <<< "$spec"
    (
      for e in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $e; done
      IFS=, ; for kv in $envs; do [ -n "$kv" ] && export "$kv"; done; unset IFS
      VR_USE_SURFACE=$surf VR_PASS_TIMES=1 VR_FRAMES=150 VR_ENGINE=v9 VR_RESULT="$(cygpath -m $O)/${tag}_r$r.txt" \
        timeout 900 $B/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py" > $O/${tag}_r$r.log 2>&1
    )
    python - "$O/${tag}_r$r.txt.passes.json" "${tag}_r$r" <<'PY'
import json, sys, os
p, tag = sys.argv[1:3]
if not os.path.exists(p): print(tag, "FAILED"); sys.exit()
o = {}
for k, v in json.load(open(p)).items():
    if k.endswith("/VolumetricReSTIR/gpu_time"): o["est"] = v["median"]
    elif k.endswith("/gpu_time") and "/VolumetricReSTIR/" in k: o[k.split("/")[-2]] = v["median"]
print("%-16s GS %6.2f  TR %6.2f  SR %6.2f  FS %6.2f  est %6.2f" % (tag, o.get("Generate Samples", 0), o.get("Temporal Reuse", 0), o.get("Spatial Reuse", 0), o.get("Final Shading", 0), o.get("est", 0)))
PY
  done
done
echo "AB_ENV DONE"
