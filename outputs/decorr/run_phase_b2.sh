#!/bin/bash
# Phase B checks the user asked for ("are the mutations right? the effect looks small"): step sizes, more
# mutations at a long history, the crashed bistro run, and the plume's mutation cost. Log: phase_b2.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/phase_b2.log
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
export STUDY_SPACING=5 STUDY_SPACING_emerald=3
say "phase B2 start"
# Step sizes: 4x longer depth steps; env rotations up to 30 deg (vs 0.1-5).
bash $O/run_study.sh one plume_g-0.9 mut1_depthbig VR_MUTATIONS=1 VR_MUT_STRAT=depth VR_MUT_STATS=1 \
    'VR_PARAMS={"mMutationDepthStepMin": 2.0, "mMutationDepthStepMax": 64.0}' 2>&1 | tee -a "$LOG"
bash $O/run_study.sh one plume_g-0.9 mut1_lightbig VR_MUTATIONS=1 VR_MUT_STRAT=light VR_MUT_STATS=1 \
    'VR_PARAMS={"mMutationDirStepMinDeg": 1.0, "mMutationDirStepMaxDeg": 30.0}' 2>&1 | tee -a "$LOG"
# More mutations at a long history, where one already halves the correlation.
bash $O/run_study.sh one plume_g-0.9 mcap_50_mut5 VR_MTHRESH=50 VR_MUTATIONS=5 VR_MUT_STRAT=light,depth VR_MUT_STATS=1 2>&1 | tee -a "$LOG"
bash $O/run_study.sh one plume_g-0.9 mcap_50_mut1_depth VR_MTHRESH=50 VR_MUTATIONS=1 VR_MUT_STRAT=depth VR_MUT_STATS=1 2>&1 | tee -a "$LOG"
# The bistro run that crashed at load (out of memory) in phase B.
bash $O/run_study.sh one bistro mcap_50_mut1 VR_MTHRESH=50 VR_MUTATIONS=1 VR_MUT_STRAT=light,depth VR_MUT_STATS=1 2>&1 | tee -a "$LOG"
say "phase B2 done"
