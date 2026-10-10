#!/bin/bash
# Why the swarm (bunnyswarm_d3) still shows artifacts after 10 mutations through OptiX (user, 2026-10-10: "even with 10
# mutations I see quite a bit of artifacts, dive into that"), and its reference again with the fixed reference tracker
# (spec V-C7: the residual ratio tracker leaked light through some bricks around lights inside the cloud). Three
# hypotheses, one run each, all through OptiX at M cap 200 like run_counts.sh's optix stage:
#   leftover correlation (slow light re-selection)  -> 20 mutations         den_optix_c200_m20
#   plain noise (192 lights, 4 candidates)           -> 10 mutations, 16 initial candidates   den_optix_c200_m10_im16
#   reuse's correlation as such                      -> decoupled history, no mutations       den_optix_dec200_m0
# The old reference is kept as ref_residual.   run_swarm_dig.sh      Log: counts.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/counts.log
L=bunnyswarm_d3
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 60; done
echo "[$(date +%H:%M:%S)] swarm dig start" >> $LOG
export STUDY_DISPLAY=960x540 STUDY_SPACING=5 STUDY_TIMEOUT=7200 STUDY_REF_FRAMES=2048
if [ -d "$O/$L/ref" ] && [ ! -d "$O/$L/ref_residual" ]; then mv "$O/$L/ref" "$O/$L/ref_residual"; fi
bash $O/run_study.sh refs $L 2>&1 | tee -a $LOG
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
MUT="VR_MUT_STRAT=light,depth,select,flight VR_MUT_AFTER_SPATIAL=1"
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
# shellcheck disable=SC2086
run $L den_optix_c200_m20 VR_DENOISER=optix $LOOK VR_MTHRESH=200 VR_MUTATIONS=20 $MUT
# shellcheck disable=SC2086
run $L den_optix_c200_m10_im16 VR_DENOISER=optix $LOOK VR_MTHRESH=200 VR_MUTATIONS=10 $MUT VR_INITIAL_M=16
# shellcheck disable=SC2086
run $L den_optix_dec200_m0 VR_DENOISER=optix $LOOK VR_MTHRESH=200 VR_DECOUPLED=1
echo "[$(date +%H:%M:%S)] swarm dig done" >> $LOG
