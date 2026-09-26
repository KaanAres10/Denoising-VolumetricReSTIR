#!/bin/bash
# Does 9.0 get a better DRIVER compile when its DXIL is new to the driver? Salts the deployed
# TraceRays.cs.slang (Generate Samples) with a never-taken branch on a unique constant, so the DXIL, and
# the NVIDIA driver's disk-cache key with it, differs from every earlier run; traces with knob_trace.sh;
# restores the shader.   salt_trace.sh <tag> <start-after-frames> [ENV=VAL ...]
tag=$1; start=$2; shift 2
R=/c/research/Denoising-VolumetricReSTIR; S=$R/build/windows-vs2022/bin/Release/shaders/RenderPasses/VolumetricReSTIR/TraceRays.cs.slang
cp -p $S $S.keep; trap 'mv $S.keep $S' EXIT
salt=$(( (RANDOM << 15 | RANDOM) + 1000000 ))
python - "$S" "$salt" <<'PY'
import sys
p, salt = sys.argv[1], sys.argv[2]
s = open(p).read()
anchor = "    if (!IsWithinRange(launchIndex, gResolution)) return;"
assert anchor in s
s = s.replace(anchor, anchor + "\n    if (gFrameCount == -%s) { gOutputColor[launchIndex] = float4(%s.0, 0, 0, 0); return; }" % (salt, salt), 1)
open(p, "w").write(s)
PY
echo "salt $salt"
sed -i "s/--start-after-frames 310/--start-after-frames $start/" $R/outputs/legacy_cmp/knob_trace.sh
bash $R/outputs/legacy_cmp/knob_trace.sh $tag "$@" | tail -1
sed -i "s/--start-after-frames $start/--start-after-frames 310/" $R/outputs/legacy_cmp/knob_trace.sh
