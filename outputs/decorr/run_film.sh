#!/bin/bash
# Real-world shots where the mutation count should matter (spec V-C7; user, 2026-10-10: "a scene representative of movies
# or real life where mutation, or multiple mutations, matters; run OptiX and RR on it; multiple different scenes"):
#   plumerig_g0.6        a concert lighting rig in stage haze (46 coloured fixtures)
#   plumewall_g0.6_d0.3  an LED video wall behind thin stage haze (32 coloured emissive tiles)
#   wdasstorm_g0.5       a night thunderstorm: lightning inside the cumulus, city lights below
#   emeraldneon_d3       a neon street in fog at night (40 coloured signs and the square's lamps)
# Per scene, one at a time: its reference, then raw / OptiX / Ray Reconstruction without reuse and with 0, 1, 3 and 10
# mutations at M cap 200 (the pass as shipped), 960x540, the Look configuration. A finished config is skipped.
#   run_film.sh [labels...]      Log: film_counts.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/film_counts.log
LABELS=${*:-plumerig_g0.6 plumewall_g0.6_d0.3 wdasstorm_g0.5 emeraldneon_d3}
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 60; done
echo "[$(date +%H:%M:%S)] film start: $LABELS" >> $LOG
export STUDY_DISPLAY=960x540 STUDY_SPACING=5 STUDY_TIMEOUT=10800 STUDY_REF_FRAMES=2048
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
MUT="VR_MUT_STRAT=light,depth,select,flight VR_MUT_AFTER_SPATIAL=1"
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
for L in $LABELS; do
    bash $O/run_study.sh refs "$L" 2>&1 | tee -a $LOG
    for P in "" "den_optix_" "den_rr_"; do
        DEN=""
        case $P in den_optix_) DEN="VR_DENOISER=optix $LOOK" ;; den_rr_) DEN="VR_DENOISER=rr $LOOK" ;; esac
        if [ -z "$P" ]; then NR=noreuse; else NR=${P}c200_noreuse; fi
        # shellcheck disable=SC2086
        run "$L" "$NR" $DEN VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
        # shellcheck disable=SC2086
        run "$L" "${P}c200_m0" $DEN VR_MTHRESH=200
        for N in 1 3 10; do
            # shellcheck disable=SC2086
            run "$L" "${P}c200_m$N" $DEN VR_MTHRESH=200 VR_MUTATIONS=$N $MUT
        done
    done
    echo "[$(date +%H:%M:%S)] film $L done" >> $LOG
done
echo "[$(date +%H:%M:%S)] film done" >> $LOG
