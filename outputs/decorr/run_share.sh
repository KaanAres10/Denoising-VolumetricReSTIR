#!/bin/bash
# Sharing less (after the root cause: mutations keep each reservoir's normalization, Sawhney et al. 2024 Eq. 17,
# so the correlation carried by shared normalizations needs less sharing, not more mutation). Two fixes from the
# literature, alone and with 5 mutations: a decoupled history (Zhou 2025, sec. 5.5.5: spatial reuse's output only
# shades) and a duplication-driven M cap (Lin et al. 2026, ReSTIR PT Enhanced). Log: share.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/share.log
export STUDY_SPACING=5 STUDY_SPACING_emerald=3
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
echo "[$(date +%H:%M:%S)] share start" >> $LOG
for L in plume_g-0.9 emerald; do
    run $L dec VR_DECOUPLED=1
    run $L dec_mcap_50 VR_DECOUPLED=1 VR_MTHRESH=50
    run $L dec_mcap_50_mut5 VR_DECOUPLED=1 VR_MTHRESH=50 VR_MUTATIONS=5
    run $L mcap_50_dup05 VR_MTHRESH=50 VR_DUP_CAP=0.5
    run $L mcap_50_dup05_mut5 VR_MTHRESH=50 VR_DUP_CAP=0.5 VR_MUTATIONS=5
done
run plume_g-0.9 dec_mcap_200 VR_DECOUPLED=1 VR_MTHRESH=200
run plume_g-0.9 mcap_200_dup05 VR_MTHRESH=200 VR_DUP_CAP=0.5
echo "[$(date +%H:%M:%S)] share done" >> $LOG
