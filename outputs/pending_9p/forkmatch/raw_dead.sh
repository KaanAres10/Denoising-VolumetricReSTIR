#!/bin/bash
# Raw estimator EXR orbit (VR_CAPTURE_RAW=1, no denoiser/tonemapper/TAA; the config of orbit_raw_v8 and
# legacy/outputs/Bistro_Raw_Today), bistro 300 frames at 1080p, with neither fix / alpha test only / both,
# scored by dead.py against the 4.x fork. EXRs deleted once scored.   raw_dead.sh
# The per-fix split was measured with temporary per-fix guards; the committed code has one switch for both,
# VR_PRE_FORK_PARITY, so "alpha" below now runs the same code as "both".
R=/c/research/Denoising-VolumetricReSTIR; cd $R
O=$R/outputs/pending_9p/forkmatch/rawexr; mkdir -p $O
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
python outputs/pending_9p/forkmatch/dead.py "4.x fork" legacy/outputs/Bistro_Raw_Today legacy
cap() { # tag slang-args
  ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
    [ -n "$2" ] && export VR_SLANG_ARGS="$2"
    rm -rf $O/$1; mkdir -p $O/$1
    VR_SCENE=bistro VR_FRAMES=300 VR_WARM=30 VR_DISPLAY=1920x1080 VR_DENOISER=none VR_CAPTURE_RAW=1 VR_OUT_DIR="$(cygpath -m $O/$1)" VR_TAG=raw \
      timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\capture_orbit.py" > $O/$1.log 2>&1 )
  python outputs/pending_9p/forkmatch/dead.py "9.0 $1" $O/$1
  rm -rf $O/$1
}
cap nofix "-DVR_PRE_FORK_PARITY=1"
cap alpha ""
cap both ""
echo RAWDEAD DONE
