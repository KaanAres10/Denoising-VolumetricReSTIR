#!/bin/bash
# Is VR_FP_MODE_VOLUME=fast less accurate? bias_test_plume.py (static plume, one point light, HDR):
# brute-force path-traced reference (precise, 4096 frames), then ReSTIR precise and fast, converged
# (4096 accumulated frames: bias) and at 64 (error at a practical sample count).
R=/c/research/Denoising-VolumetricReSTIR; cd $R
O=$R/outputs/pending_9p/fastmath/bias; mkdir -p $O
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
run() { # tag mode frames fpmode
  ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
    [ -n "$4" ] && export VR_FP_MODE_VOLUME=$4
    VR_MODE=$2 VR_FRAMES=$3 VR_TAG=_$1 VR_EXIT=1 VR_OUT_DIR="$(cygpath -w $O)" timeout 3000 ./build/windows-vs2022/bin/Release/Mogwai.exe \
      --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\bias_test_plume.py" > $O/$1.log 2>&1 )
  echo "$1: $(ls $O/plume_$2_$1.AccumulatePass.output.*.exr 2>/dev/null | wc -l) exr"
}
run ref reference 4096 ""
run precise4096 restir 4096 ""
run fast4096 restir 4096 fast
run precise64 restir 64 ""
run fast64 restir 64 fast
echo BIAS RUNS DONE
