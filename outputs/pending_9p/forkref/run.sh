#!/bin/bash
# ReSTIR vs brute-force path tracing at the verify pose, both engines (reference_pose.py and the legacy
# twin). run.sh <engine fork|v9> <mode reference|restir> <frames> <spp> <tag> [ENV=VAL ...]
R=/c/research/Denoising-VolumetricReSTIR; cd $R
O=$R/outputs/pending_9p/forkref/cap
eng=$1 mode=$2 frames=$3 spp=$4 tag=$5; shift 5
tasklist 2>/dev/null | grep -qi mogwai && { echo "Mogwai running, abort"; exit 1; }
mkdir -p $O/$tag; rm -f $O/$tag/*
t0=$(date +%s)
( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
  for kv in "$@"; do export "$kv"; done
  export VR_MODE=$mode VR_FRAMES=$frames VR_SPP=$spp VR_TAG=$tag
  if [ $eng = fork ]; then
    cd $R/legacy; VR_OUT_DIR="$(cygpath -w $O/$tag)" timeout 10800 ./Bin/x64/Release/Mogwai.exe --script "$(cygpath -w $R/legacy/Scripts/_reference_pose_legacy.py)" > $O/$tag.log 2>&1
  else
    VR_OUT_DIR="$(cygpath -m $O/$tag)" timeout 10800 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\reference_pose.py" > $O/$tag.log 2>&1
  fi )
echo "$tag: $(ls $O/$tag/*.exr 2>/dev/null | wc -l) exr, $(( $(date +%s) - t0 )) s"
