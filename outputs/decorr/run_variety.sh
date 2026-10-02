#!/bin/bash
# A variety of situations where mutations help, each shown the way the user liked best (paper_figure.py: one denoised
# frame, zoom boxes, error row): plain ReSTIR vs the same with 5 moves of all four kinds after spatial reuse, both
# through OptiX, at M cap 200 (no decoupled history). One scene per effect: colour among many lights, large area
# lights, city fog lit by street lamps, a spotlight beam, a lamp inside the medium, a backlit rim, sky-lit smoke,
# self-emission, shadow stripes. Missing references are rendered first. Log: variety.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/variety.log
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
MUT="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
export STUDY_SPACING=5 STUDY_SPACING_emeraldnight_d3=3 STUDY_REF_FRAMES=2048
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
echo "[$(date +%H:%M:%S)] variety start" >> $LOG
for L in bunnylanterns bunnysoftbox emeraldnight_d3 bunnyspot bunnyinside plumeback_g0.9 plume_g-0.9 explosion bunnystripes bunnyback_g0.8; do
    case $L in emeraldnight*|explosion|plume_g-0.9) export STUDY_TIMEOUT=7200 ;; *) export STUDY_TIMEOUT=3600 ;; esac
    bash $O/run_study.sh refs $L 2>&1 | tee -a $LOG  # (skips an existing reference)
    # shellcheck disable=SC2086
    run $L den_optix_mut0cap200 VR_DENOISER=optix $LOOK VR_MTHRESH=200
    # shellcheck disable=SC2086
    run $L den_optix_mut5cap200 VR_DENOISER=optix $LOOK VR_MTHRESH=200 $MUT
done
echo "[$(date +%H:%M:%S)] variety done" >> $LOG
