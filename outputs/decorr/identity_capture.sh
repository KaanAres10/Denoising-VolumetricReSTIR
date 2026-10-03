#!/bin/bash
# Byte-identity captures for the two-bounce change: outputs/decorr/identity/<tag>/<config>/*.exr.
# Small and deterministic: 640x360, 1 chain x 2 frames, 32 warm-up frames.
set -u
tag=$1
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
MUT="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight VR_MUT_STATS=0 VR_MUT_AFTER_SPATIAL=1"
cap() {  # name, env...
    local d="$R/outputs/decorr/identity/$tag/$1"; shift
    mkdir -p "$d"
    ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
      export VR_DISPLAY=640x360 VR_CHAINS=1 VR_PER_CHAIN=2 VR_WARM=32 VR_SPACING=1 VR_IDS=0 "$@"
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe \
        --script 'C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py' > "$d/run.log" 2>&1 )
    echo "$tag/$(basename "$d"): $(ls "$d"/*.exr 2>/dev/null | wc -l) exr"
}
# shellcheck disable=SC2086
cap b1_mut0_explosion VR_SCENE=explosiondusk VR_MTHRESH=200
# shellcheck disable=SC2086
cap b1_mut5_explosion VR_SCENE=explosiondusk VR_MTHRESH=200 $MUT
# shellcheck disable=SC2086
cap b1_mut5_softbox VR_SCENE=bunnysoftbox VR_MTHRESH=200 $MUT
# shellcheck disable=SC2086
cap b1_mut5_cathedral VR_SCENE=bunnycathedral VR_DENSITY_MULT=0.3 VR_MTHRESH=200 $MUT
# shellcheck disable=SC2086
cap b2_mut0_explosion VR_SCENE=explosiondusk VR_MAX_BOUNCES=2 VR_MTHRESH=200
# shellcheck disable=SC2086
cap b2_mut0_cathedral VR_SCENE=bunnycathedral VR_DENSITY_MULT=0.3 VR_MAX_BOUNCES=2 VR_MTHRESH=200
