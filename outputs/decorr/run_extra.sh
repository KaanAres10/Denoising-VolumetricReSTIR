#!/bin/bash
# Follow-up to Phase A (queued 2026-09-27), after it finishes -- two Mogwai instances would not fit the
# 8 GB GPU:
#   1. path-traced references for the scenes that had none (wdas, bunny, bunny_g0.8, explosion, plume);
#   2. re-render every run scored before m_corr measured correlation inside the medium, or that scored
#      it on its own mask while a baseline existed: every volume scene's survey, plume_g-0.9's ablations
#      and bistro's survey. After step 1, so they are scored against a reference too;
#      plume_g-0.9's denoised runs are redone too: they predate the env-background fix (924506c);
#   3. the WDAS density sweep of Lin et al. 2021's figure (0.2x / 3x; 1x is the wdas survey);
#   4. the summary and every artifact figure.
# Log: outputs/decorr/extra.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/extra.log
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

stale() {  # corr.json: no medium block, or a medium block on the run's own mask although it has a baseline
    python - "$1" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
m = r.get("medium")
sys.exit(0 if m is None or ("baseline" in r and m.get("mask") != "baseline") else 1)
PY
}

requeue() {  # label config...: set stale scores aside (c.corr.v1.json), so the stage renders them again
    local l=$1 c f
    shift
    for c in "$@"; do
        f=$O/$l/$c/c.corr.json
        if [ -f "$f" ] && stale "$f"; then mv "$f" "$O/$l/$c/c.corr.v1.json"; say "requeue $l/$c"; fi
    done
}

say "waiting for phase A"
until grep -q "phase A done" $O/phase_a.log; do sleep 60; done
export STUDY_SPACING=5  # every label below was captured at spacing 5 (what their bursts gave)
for l in wdas bunny bunny_g0.8 explosion plume; do bash $O/run_study.sh refs "$l" 2>&1 | tee -a "$LOG"; done
for l in plume explosion bunny bunny_g0.8 wdas bistro; do
    requeue "$l" noreuse shipped
    bash $O/run_study.sh survey "$l" 2>&1 | tee -a "$LOG"
done
requeue plume_g-0.9 noreuse shipped temporal_only spatial_only mcap_1 mcap_10 mcap_20 mcap_50 mcap_200 \
    radius_3 radius_30 rounds_3 pixel_offsets
bash $O/run_study.sh deep plume_g-0.9 2>&1 | tee -a "$LOG"
# The denoised plume runs predate the env-background fix (924506c): they are Phase B's baseline, so redo them.
requeue plume_g-0.9 $(for d in optix oidn nrd_RelaxDiffuseSh nrd_ReblurDiffuseSh rr; do echo den_${d}_noreuse den_${d}_shipped; done)
bash $O/run_study.sh denoise plume_g-0.9 2>&1 | tee -a "$LOG"
for l in wdas_d0.2 wdas_d3; do
    bash $O/run_study.sh refs "$l" 2>&1 | tee -a "$LOG"
    bash $O/run_study.sh survey "$l" 2>&1 | tee -a "$LOG"
done
python $O/summarize.py $O | tee -a "$LOG"
for l in wdas wdas_d0.2 wdas_d3 bunny bunny_g0.8 explosion plume bistro emerald plume_g-0.9; do
    python $O/artifacts.py $O "$l" 2>&1 | tail -1 | tee -a "$LOG"
done
say "extra done"
