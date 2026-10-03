#!/bin/bash
# The variety set (run_variety.sh, run_showcase.sh) through DLSS Ray Reconstruction instead of OptiX (user request,
# 2026-10-03): plain ReSTIR vs the same with 5 moves of all four kinds after spatial reuse, at M cap 200, no
# decoupled history, RR at native resolution (DLAA). Gallery order (strongest OptiX effect first), the night street
# last. References exist already. Log: rr.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/rr.log
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
MUT="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
export STUDY_SPACING=5 STUDY_SPACING_emeraldnight_d3=3
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
echo "[$(date +%H:%M:%S)] rr start" >> $LOG
for L in bunnycathedral_d0.3 bunnyspot bunnysoftbox bunnyinside bunnyback_g0.8 bunnystripes explosion bunnylanterns \
         wdassunset_g0.85 plumeback_g0.9 plumeconcert_g0.6 emeraldnight_d3; do
    case $L in emeraldnight*|explosion|wdassunset*|plumeconcert*) export STUDY_TIMEOUT=7200 ;; *) export STUDY_TIMEOUT=3600 ;; esac
    # shellcheck disable=SC2086
    run $L den_rr_mut0cap200 VR_DENOISER=rr $LOOK VR_MTHRESH=200
    # shellcheck disable=SC2086
    run $L den_rr_mut5cap200 VR_DENOISER=rr $LOOK VR_MTHRESH=200 $MUT
done
echo "[$(date +%H:%M:%S)] rr done" >> $LOG
