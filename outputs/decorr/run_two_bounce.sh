#!/bin/bash
# The variety comparison at two bounces: per first-round scene, plain ReSTIR vs 5 moves of every kind (M cap 200,
# no decoupled history), through OptiX and DLSS Ray Reconstruction. References come from run_b2_bias.sh. Log: b2.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/b2.log
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
MUT="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
export STUDY_SPACING=5
# 4 chains (K = 40) rather than the study's 10: at 2 bounces and 1080p a chain is 800 warm-up frames, and the
# cathedral's (ray queries at the second bounce) measured ~21 min each -- 10 would pass any sane timeout. The figures
# use the first frame of chains 0 and 1, so their numbers are unaffected; only m_corr's statistics get coarser.
# The explosion's pairs ran with 10 before this (K = 100).
export STUDY_CHAINS=4
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
echo "[$(date +%H:%M:%S)] b2 denoised start" >> $LOG
for L in explosiondusk_b2 bunnycathedral_d0.3_b2 bunnyback_g0.8_b2 bunnysoftbox_b2 wdassunset_g0.85_b2; do
    export STUDY_TIMEOUT=21600
    for den in optix rr; do
        # shellcheck disable=SC2086
        run $L den_${den}_mut0cap200 VR_DENOISER=$den $LOOK VR_MTHRESH=200
        # shellcheck disable=SC2086
        run $L den_${den}_mut5cap200 VR_DENOISER=$den $LOOK VR_MTHRESH=200 $MUT
    done
done
echo "[$(date +%H:%M:%S)] b2 denoised done" >> $LOG
