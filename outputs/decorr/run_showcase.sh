#!/bin/bash
# What a viewer sees (spec V-B10): the scenes where mutations help most, through a denoiser. A denoiser removes
# per-pixel noise but keeps reuse's blotches -- correlated error looks like signal to it -- so the denoised frame
# shows ReSTIR's artifacts plainly, and what mutations alone do to them. No decoupled history: plain ReSTIR vs the
# same ReSTIR with 5 moves of all four kinds after spatial reuse, at the shipped cap and at M cap 200, each next to
# the denoiser's no-reuse run (its baseline). OptiX, with the Look settings the denoiser runs use. Log: showcase.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/showcase.log
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
MUT="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
export STUDY_SPACING=5
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
echo "[$(date +%H:%M:%S)] showcase start" >> $LOG
for L in plumeconcert_g0.6 bunnycathedral_d0.3 bunnylanterns bunnysoftbox wdassunset_g0.85; do
    case $L in wdassunset*) export STUDY_TIMEOUT=7200 ;; *) export STUDY_TIMEOUT=2400 ;; esac
    # shellcheck disable=SC2086
    run $L den_optix_noreuse VR_DENOISER=optix $LOOK VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
    # shellcheck disable=SC2086
    run $L den_optix_mut0ship VR_DENOISER=optix $LOOK
    # shellcheck disable=SC2086
    run $L den_optix_mut5ship VR_DENOISER=optix $LOOK $MUT
    # shellcheck disable=SC2086
    run $L den_optix_mut0cap200 VR_DENOISER=optix $LOOK VR_MTHRESH=200
    # shellcheck disable=SC2086
    run $L den_optix_mut5cap200 VR_DENOISER=optix $LOOK VR_MTHRESH=200 $MUT
done
echo "[$(date +%H:%M:%S)] showcase done" >> $LOG
