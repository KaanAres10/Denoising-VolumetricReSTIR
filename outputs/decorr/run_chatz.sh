#!/bin/bash
# DIAGNOSTIC (spec V-C7): the swarm's normalization c_hat = runningSum / M, for chat_maps.py. Before running, patch the RUNTIME
# copy of FinalShading.cs.slang (build/.../shaders/RenderPasses/VolumetricReSTIR/) so the sample identity's .z holds
# res.runningSum / res.M instead of the light id (the capture keeps .xyz only); the trap restores it from the source.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
RT=build/windows-vs2022/bin/Release/shaders/RenderPasses/VolumetricReSTIR/FinalShading.cs.slang
restore() { cp Source/RenderPasses/VolumetricReSTIR/FinalShading.cs.slang "$RT"; cmp "$RT" Source/RenderPasses/VolumetricReSTIR/FinalShading.cs.slang && echo "runtime FinalShading restored" >> $O/counts.log; }
trap restore EXIT
export STUDY_DISPLAY=960x540 STUDY_SPACING=5 STUDY_TIMEOUT=7200
MUT="VR_MUTATIONS=10 VR_MUT_STRAT=light,depth,select,flight VR_MUT_AFTER_SPATIAL=1"
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $O/counts.log; }
run bunnyswarm_d3 chatz_c200_m0 VR_MTHRESH=200
# shellcheck disable=SC2086
run bunnyswarm_d3 chatz_c200_m10 VR_MTHRESH=200 $MUT
run bunnyswarm_d3 chatz_dec200_m0 VR_MTHRESH=200 VR_DECOUPLED=1
echo "[$(date +%H:%M:%S)] chatz done" >> $O/counts.log
