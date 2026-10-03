#!/bin/bash
# The two-bounce bias gate (spec): per first-round scene, reference, no reuse, M cap 200 plain, M cap 200 + 5 moves
# of every kind, and M cap 200 + 5 light-only moves (plan Review Focus 1-2: emission paths, the extra bounce every
# p_hat sees). Log: b2.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/b2.log
ALL="light,depth,select,flight,direction,distance,rebounce"
export STUDY_SPACING=5 STUDY_REF_FRAMES=2048
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
echo "[$(date +%H:%M:%S)] b2 bias start" >> $LOG
for L in explosiondusk_b2 bunnycathedral_d0.3_b2 bunnyback_g0.8_b2 bunnysoftbox_b2 wdassunset_g0.85_b2; do
    case $L in wdassunset*|explosion*) export STUDY_TIMEOUT=10800 ;; *) export STUDY_TIMEOUT=7200 ;; esac
    bash $O/run_study.sh refs $L 2>&1 | tee -a $LOG
    run $L noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
    run $L mcap200 VR_MTHRESH=200
    run $L mcap200_mut5b2 VR_MTHRESH=200 VR_MUTATIONS=5 VR_MUT_STRAT=$ALL VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1
    run $L mcap200_mut5light VR_MTHRESH=200 VR_MUTATIONS=5 VR_MUT_STRAT=light,select VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1
done
echo "[$(date +%H:%M:%S)] b2 bias done" >> $LOG
