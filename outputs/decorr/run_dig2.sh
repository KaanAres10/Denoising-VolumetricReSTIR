#!/bin/bash
# After run_swarm_dig.sh: what mutations cannot reach (spec V-C7). Eq. 16 keeps the reservoir's normalization
# runningSum/M, which reuse spreads between neighbours and over a 200-frame history; a decoupled history (spatial
# reuse's output kept out of it) shares it less. Both scenes through OptiX at M cap 200: decoupled with and without 10
# mutations (the swarm's decoupled run without mutations is run_swarm_dig.sh's).   run_dig2.sh      Log: counts.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/counts.log
until grep -q "swarm dig done" $LOG 2>/dev/null; do sleep 60; done
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 60; done
echo "[$(date +%H:%M:%S)] dig2 start" >> $LOG
export STUDY_DISPLAY=960x540 STUDY_SPACING=5 STUDY_TIMEOUT=7200
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
# shellcheck disable=SC2086
run bunnyswarm_d3 den_optix_dec200_m10 VR_DENOISER=optix $LOOK VR_MTHRESH=200 VR_DECOUPLED=1 VR_MUTATIONS=10 \
    VR_MUT_STRAT=light,depth,select,flight VR_MUT_AFTER_SPATIAL=1
# shellcheck disable=SC2086
run bunnyclosebox_b2 den_optix_dec200_m0 VR_DENOISER=optix $LOOK VR_MTHRESH=200 VR_DECOUPLED=1
# shellcheck disable=SC2086
run bunnyclosebox_b2 den_optix_dec200_m10 VR_DENOISER=optix $LOOK VR_MTHRESH=200 VR_DECOUPLED=1 VR_MUTATIONS=10 \
    VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce VR_MUT_AFTER_SPATIAL=1
echo "[$(date +%H:%M:%S)] dig2 done" >> $LOG
