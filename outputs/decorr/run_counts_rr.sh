#!/bin/bash
# The swarm's mutation counts through both denoisers (user, 2026-10-10: "focus on mutations: run 1 mutation with RR as
# well, and a really high number of mutations, on both OptiX and RR"). M cap 200, 960x540, the Look configuration;
# OptiX already has 0 / 1 / 3 / 10 / 20 (run_counts.sh, run_swarm_dig.sh) and RR 0 / 10 (run_rr_swarm.sh). 64 is the UI's
# maximum count. Plus the raw frames at 64 for count_curve.py.   run_counts_rr.sh      Log: counts.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/counts.log
L=bunnyswarm_d3
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 60; done
echo "[$(date +%H:%M:%S)] counts rr start" >> $LOG
export STUDY_DISPLAY=960x540 STUDY_SPACING=5 STUDY_TIMEOUT=10800
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
MUT="VR_MUT_STRAT=light,depth,select,flight VR_MUT_AFTER_SPATIAL=1"
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
for N in 1 3 20 64; do
    # shellcheck disable=SC2086
    run $L den_rr_c200_m$N VR_DENOISER=rr $LOOK VR_MTHRESH=200 VR_MUTATIONS=$N $MUT
done
# shellcheck disable=SC2086
run $L den_optix_c200_m64 VR_DENOISER=optix $LOOK VR_MTHRESH=200 VR_MUTATIONS=64 $MUT
# shellcheck disable=SC2086
run $L c200_m64 VR_MTHRESH=200 VR_MUTATIONS=64 $MUT
echo "[$(date +%H:%M:%S)] counts rr done" >> $LOG
