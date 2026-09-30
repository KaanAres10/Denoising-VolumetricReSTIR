#!/bin/bash
# What a denoiser makes of the configurations (the visual test: a denoiser removes decorrelated noise, not
# blotches). OptiX and NRD RELAX-SH on the 8-light bunny, OptiX on emerald: no reuse, shipped, M cap 50 and
# decoupled M cap 200, each with and without 5 mutations of every kind after spatial reuse. Names match
# run_study.sh's den_*_mut* pattern so each is scored against its own denoiser's no-reuse run. Log: select.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/select.log
export STUDY_SPACING=5 STUDY_SPACING_emerald=3 STUDY_TIMEOUT=7200
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
MUT="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select VR_MUT_AFTER_SPATIAL=1"
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
echo "[$(date +%H:%M:%S)] den2 start" >> $LOG
for spec in bunnyparty:optix bunnyparty:nrd:RelaxDiffuseSh emerald:optix; do
    L=${spec%%:*}; rest=${spec#*:}; mode=${rest%%:*}; name=$mode; extra=""
    [ "$mode" = nrd ] && { name="nrd_${rest#*:}"; extra="VR_NRD_METHOD=${rest#*:}"; }
    # shellcheck disable=SC2086
    run $L "den_${name}_noreuse" VR_DENOISER=$mode $extra $LOOK VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
    # shellcheck disable=SC2086
    run $L "den_${name}_mut0ship" VR_DENOISER=$mode $extra $LOOK
    # shellcheck disable=SC2086
    run $L "den_${name}_mut5ship" VR_DENOISER=$mode $extra $LOOK $MUT
    # shellcheck disable=SC2086
    run $L "den_${name}_mut0cap50" VR_DENOISER=$mode $extra $LOOK VR_MTHRESH=50
    # shellcheck disable=SC2086
    run $L "den_${name}_mut5cap50" VR_DENOISER=$mode $extra $LOOK VR_MTHRESH=50 $MUT
    # shellcheck disable=SC2086
    run $L "den_${name}_mut0dec200" VR_DENOISER=$mode $extra $LOOK VR_DECOUPLED=1 VR_MTHRESH=200
    # shellcheck disable=SC2086
    run $L "den_${name}_mut5dec200" VR_DENOISER=$mode $extra $LOOK VR_DECOUPLED=1 VR_MTHRESH=200 $MUT
done
echo "[$(date +%H:%M:%S)] den2 done" >> $LOG
