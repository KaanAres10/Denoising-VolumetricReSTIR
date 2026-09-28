#!/bin/bash
# What the denoisers make of the long-history configurations (V-B6 said: judge those denoised). OptiX and NRD
# RELAX-SH on M cap 50, M cap 50 + 5 mutations and the decoupled history at M cap 200. Log: share.log.
# Names match run_study.sh's den_*_mut* pattern so each is scored against its own denoiser's no-reuse run.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/share.log
export STUDY_SPACING=5 STUDY_SPACING_emerald=3
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
echo "[$(date +%H:%M:%S)] share_den start" >> $LOG
for L in plume_g-0.9 emerald; do
    for spec in optix nrd:RelaxDiffuseSh; do
        mode=${spec%%:*}; name=$mode; extra=""
        [ "$mode" = nrd ] && { name="nrd_${spec#*:}"; extra="VR_NRD_METHOD=${spec#*:}"; }
        if [ ! -f "$O/$L/den_${name}_shipped/c.corr.json" ]; then  # emerald has no denoised baselines yet
            # shellcheck disable=SC2086
            run $L "den_${name}_noreuse" VR_DENOISER=$mode $extra $LOOK VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
            # shellcheck disable=SC2086
            run $L "den_${name}_shipped" VR_DENOISER=$mode $extra $LOOK
        fi
        # shellcheck disable=SC2086
        run $L "den_${name}_mut0cap50" VR_DENOISER=$mode $extra $LOOK VR_MTHRESH=50
        # shellcheck disable=SC2086
        run $L "den_${name}_mut5cap50" VR_DENOISER=$mode $extra $LOOK VR_MTHRESH=50 VR_MUTATIONS=5
        # shellcheck disable=SC2086
        run $L "den_${name}_mut0dec200" VR_DENOISER=$mode $extra $LOOK VR_MTHRESH=200 VR_DECOUPLED=1
    done
done
# The emerald duplication-cap runs failed before the surface-scene fix of the DuplicationMap pass; rerun them.
run emerald mcap_50_dup05 VR_MTHRESH=50 VR_DUP_CAP=0.5
echo "[$(date +%H:%M:%S)] share_den done" >> $LOG
