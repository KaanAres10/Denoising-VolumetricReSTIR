#!/bin/bash
# The reuse radius (Junkins et al. 2026, Sec. 6: radius trades error for correlation; Lin et al. 2021 Fig. 15)
# with a long history, and with mutations on top. Log: share.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/share.log
export STUDY_SPACING=5 STUDY_SPACING_emerald=3
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
echo "[$(date +%H:%M:%S)] share2 start" >> $LOG
for L in plume_g-0.9 emerald; do
    run $L mcap_50_r30 VR_MTHRESH=50 VR_SR_RADIUS=30
    run $L mcap_50_r30_mut5 VR_MTHRESH=50 VR_SR_RADIUS=30 VR_MUTATIONS=5
done
run emerald dec_mcap_200 VR_DECOUPLED=1 VR_MTHRESH=200
echo "[$(date +%H:%M:%S)] share2 done" >> $LOG
