#!/bin/bash
# Root cause of the small mutation effect (user: "investigate what went wrong"). Hypothesis: most of reuse's
# correlation is the SHARED RESAMPLING WEIGHT (normalisation), which Eq. 16 preserves by construction; mutations
# only diversify which sample carries it. Predictions tested here: (1) spatial-only correlation does not move
# with mutations (they run before spatial reuse, on unshared samples); (2) many mutations saturate far above no
# reuse. Log: rootcause.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/rootcause.log
export STUDY_SPACING=5
echo "[$(date +%H:%M:%S)] root cause start" >> $LOG
bash $O/run_study.sh one plume_g-0.9 spatial_only_mut5 VR_NO_TEMPORAL=1 VR_MUTATIONS=5 VR_MUT_STRAT=depth VR_MUT_STATS=1 2>&1 | tee -a $LOG
bash $O/run_study.sh one plume_g-0.9 mut32_depth VR_MUTATIONS=32 VR_MUT_STRAT=depth VR_MUT_STATS=1 2>&1 | tee -a $LOG
bash $O/run_study.sh one plume_g-0.9 mcap_50_mut32_depth VR_MTHRESH=50 VR_MUTATIONS=32 VR_MUT_STRAT=depth VR_MUT_STATS=1 2>&1 | tee -a $LOG
echo "[$(date +%H:%M:%S)] root cause done" >> $LOG
