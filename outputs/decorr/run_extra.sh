#!/bin/bash
# Follow-up to Phase A, queued at the user's request (2026-09-27): path-traced references for the scenes
# whose artifact figures had none (wdas, bunny, bunny_g0.8, explosion, plume), and the WDAS density sweep
# of Lin et al. 2021's figure (0.2x / 1x / 3x; 1x is Phase A's wdas survey). Waits for Phase A to finish
# -- two Mogwai instances would not fit the 8 GB GPU -- then swaps in run_study.sh.new (density labels;
# editing run_study.sh in place would corrupt the instance bash is still reading), runs, and regenerates
# every artifact figure. Log: outputs/decorr/extra.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/extra.log
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

say "waiting for phase A"
until grep -q "phase A done" $O/phase_a.log; do sleep 60; done
[ -f $O/run_study.sh.new ] && mv $O/run_study.sh.new $O/run_study.sh
export STUDY_SPACING=5   # every scene's burst gave 5 (emerald 3), and wdas_d* are wdas
for l in wdas bunny bunny_g0.8 explosion plume; do bash $O/run_study.sh refs "$l" 2>&1 | tee -a "$LOG"; done
for l in wdas_d0.2 wdas_d3; do
    bash $O/run_study.sh refs "$l" 2>&1 | tee -a "$LOG"
    bash $O/run_study.sh survey "$l" 2>&1 | tee -a "$LOG"
done
python $O/summarize.py $O | tee -a "$LOG"
for l in wdas wdas_d0.2 wdas_d3 bunny bunny_g0.8 explosion plume bistro emerald plume_g-0.9; do
    python $O/artifacts.py $O "$l" 2>&1 | tail -1 | tee -a "$LOG"
done
say "extra done"
