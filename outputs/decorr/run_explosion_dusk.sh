#!/bin/bash
# The explosion as the paper shows it (vr_graph.load_explosion_dusk: skylight-dusk.exr with the paper's rotation
# converted to Falcor 9, temperature scale 1000 -- user: "the explosion seems too bright, the background differs"):
# its reference, the no-reuse baseline (the medium mask), and the variety pair through OptiX and through DLSS Ray
# Reconstruction (M cap 200, 0 vs 5 mutations, no decoupled history). Log: rr.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/rr.log
L=explosiondusk
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
MUT="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
export STUDY_SPACING=5 STUDY_REF_FRAMES=2048 STUDY_TIMEOUT=7200
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
echo "[$(date +%H:%M:%S)] explosiondusk start" >> $LOG
bash $O/run_study.sh refs $L 2>&1 | tee -a $LOG
run $L noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
for den in optix rr; do
    # shellcheck disable=SC2086
    run $L den_${den}_mut0cap200 VR_DENOISER=$den $LOOK VR_MTHRESH=200
    # shellcheck disable=SC2086
    run $L den_${den}_mut5cap200 VR_DENOISER=$den $LOOK VR_MTHRESH=200 $MUT
done
echo "[$(date +%H:%M:%S)] explosiondusk done" >> $LOG
