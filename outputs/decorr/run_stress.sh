#!/bin/bash
# Artifact atlas (spec V-B9): stress scenes built to provoke volumetric ReSTIR's artifacts -- the bunny cloud
# under three coloured point lights (light choice = colour), one white light in front, one behind with a
# forward phase function, the heterogeneous plume under one light, a dense bunny -- scored for luminance AND
# colour correlation and light-choice clumping. Then emerald and bistro re-scored with the colour metrics.
# Log: stress.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/stress.log
export STUDY_SPACING=5 STUDY_SPACING_emerald=3 STUDY_REF_FRAMES=2048 STUDY_TIMEOUT=5400
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
echo "[$(date +%H:%M:%S)] stress start" >> $LOG
for L in bunnyrgb bunnyone bunnyback_g0.8 plumeone bunnyone_d5; do
    bash $O/run_study.sh refs $L 2>&1 | tee -a $LOG
    run $L noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
    run $L shipped
    run $L mcap_50 VR_MTHRESH=50
    run $L mcap_50_mut5 VR_MTHRESH=50 VR_MUTATIONS=5
    run $L dec_mcap_200 VR_DECOUPLED=1 VR_MTHRESH=200
done
echo "[$(date +%H:%M:%S)] stress done" >> $LOG
