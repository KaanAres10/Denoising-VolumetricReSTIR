#!/bin/bash
# Phase B evaluation (plan Task 11), with the Phase A follow-up in between, in GPU order. Log: phase_b.log.
#   1. bistro's mutation matrix first: its Phase A baseline is unaffected by the env-background fix
#      (924506c), so the first results land soonest; plus the equal-time rivals of 1 / 5 mutations, from
#      timing/ (1 mutation +13.5 ms ~ mInitialM 8; 5 mutations +33 ms ~ mInitialM 14);
#   2. run_extra.sh: references, the fixed-build re-renders (volume surveys, plume_g-0.9's ablations and
#      denoised runs -- Phase B's baseline there), the WDAS density sweep, the artifact figures;
#   3. the mutation matrix on plume_g-0.9 and emerald;
#   4. one mutation on every survey scene and the density sweep;
#   5. every denoiser with one mutation, against the same denoiser as shipped (bistro, plume_g-0.9);
#   6. summary.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/phase_b.log
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
export STUDY_SPACING=5 STUDY_SPACING_emerald=3  # the bursts' spacings (Phase A)
say "phase B start"
# bistro's survey predates the medium metric: redo it first, so its mutation runs have the baseline's mask.
for c in noreuse shipped; do
    f=$O/bistro/$c/c.corr.json
    if [ -f "$f" ] && ! grep -q '"medium"' "$f"; then mv "$f" "$O/bistro/$c/c.corr.v1.json"; say "requeue bistro/$c"; fi
done
bash $O/run_study.sh survey bistro 2>&1 | tee -a "$LOG"
bash $O/run_study.sh mutate bistro 2>&1 | tee -a "$LOG"
bash $O/run_study.sh one bistro initm_8 VR_INITIAL_M=8 2>&1 | tee -a "$LOG"
bash $O/run_study.sh one bistro initm_14 VR_INITIAL_M=14 2>&1 | tee -a "$LOG"
say "follow-up (run_extra.sh)"
bash $O/run_extra.sh > $O/extra.stdout 2>&1
tail -3 $O/extra.log | tee -a "$LOG"
for l in plume_g-0.9 emerald; do bash $O/run_study.sh mutate "$l" 2>&1 | tee -a "$LOG"; done
bash $O/run_study.sh mutate1 plume bunny bunny_g0.8 explosion wdas wdas_d0.2 wdas_d3 2>&1 | tee -a "$LOG"
for l in bistro plume_g-0.9; do bash $O/run_study.sh denoise "$l" 1 2>&1 | tee -a "$LOG"; done
bash $O/run_study.sh summary 2>&1 | tee -a "$LOG"
say "phase B done"
