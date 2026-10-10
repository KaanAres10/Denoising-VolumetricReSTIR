#!/bin/bash
# The swarm (bunnyswarm_d3) through DLSS Ray Reconstruction (user, 2026-10-10: "show denoised versions as well using RR"),
# the same configurations as the OptiX runs and chat_maps.py's figure: no reuse, plain ReSTIR, 10 mutations, decoupled
# history with and without 10 mutations, M cap 200, 960x540, the Look configuration of the denoiser studies.
#   run_rr_swarm.sh      Log: counts.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/counts.log
L=bunnyswarm_d3
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 60; done
echo "[$(date +%H:%M:%S)] rr swarm start" >> $LOG
export STUDY_DISPLAY=960x540 STUDY_SPACING=5 STUDY_TIMEOUT=7200
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
MUT="VR_MUTATIONS=10 VR_MUT_STRAT=light,depth,select,flight VR_MUT_AFTER_SPATIAL=1"
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
# shellcheck disable=SC2086
run $L den_rr_c200_noreuse VR_DENOISER=rr $LOOK VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
# shellcheck disable=SC2086
run $L den_rr_c200_m0 VR_DENOISER=rr $LOOK VR_MTHRESH=200
# shellcheck disable=SC2086
run $L den_rr_c200_m10 VR_DENOISER=rr $LOOK VR_MTHRESH=200 $MUT
# shellcheck disable=SC2086
run $L den_rr_dec200_m0 VR_DENOISER=rr $LOOK VR_MTHRESH=200 VR_DECOUPLED=1
# shellcheck disable=SC2086
run $L den_rr_dec200_m10 VR_DENOISER=rr $LOOK VR_MTHRESH=200 VR_DECOUPLED=1 $MUT
echo "[$(date +%H:%M:%S)] rr swarm done" >> $LOG
