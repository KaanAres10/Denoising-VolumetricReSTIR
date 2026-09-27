#!/bin/bash
# Phase A of the decorrelation study, end to end (plan Task 6), resumable: re-running skips every config
# already scored. Progress goes to outputs/decorr/phase_a.log.
#
#   1. burst on every scene; each scene's capture spacing = the first lag at which the burst's temporal
#      autocorrelation drops below 0.05, rounded up to an odd number (coprime with the 16-frame R2 period)
#   2. survey (no reuse vs as shipped) on every scene, at that spacing
#   3. deep ablations + references on bistro, plume_g-0.9 and the other scene whose reuse adds the most
#      correlation (largest robust delta rho(8) in the survey)
#   4. every denoiser on bistro and plume_g-0.9
#   5. summary.tsv and sheets
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/phase_a.log
ALL="plume plume_g-0.9 bistro explosion emerald bunny bunny_g0.8 wdas fireplume dust"
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

spacing_of() {  # label -> spacing from its burst, default 33
    python - "$O/$1/burst/c.corr.json" <<'PY'
import json, sys
try:
    lag = json.load(open(sys.argv[1]))["temporal"]["lag_below_0.05"]
except Exception:
    lag = 33
lag = max(int(lag), 1)
print(lag if lag % 2 else lag + 1)
PY
}

say "phase A start"
for l in $ALL; do bash $O/run_study.sh burst "$l" 2>&1 | tee -a "$LOG"; done
for l in $ALL; do
    s=$(spacing_of "$l")
    say "spacing $l = $s"
    export "STUDY_SPACING_$(echo "$l" | tr -- '-.' '__')=$s"
done
# plume_g-0.9 is always a deep scene: its reference first, so its survey rows are scored against it.
bash $O/run_study.sh refs plume_g-0.9 2>&1 | tee -a "$LOG"
for l in $ALL; do bash $O/run_study.sh survey "$l" 2>&1 | tee -a "$LOG"; done
python $O/summarize.py $O >> "$LOG"
third=$(python - "$O/summary.tsv" <<'PY'
import csv, sys
best, label = None, None
for r in csv.DictReader(open(sys.argv[1]), delimiter="\t"):
    if r["config"] != "shipped" or r["label"] in ("bistro", "plume_g-0.9") or not r["delta_robust_r8"]:
        continue
    v = float(r["delta_robust_r8"])
    if best is None or v > best:
        best, label = v, r["label"]
print(label or "plume")
PY
)
say "deep scenes: bistro plume_g-0.9 $third"
bash $O/run_study.sh refs "$third" 2>&1 | tee -a "$LOG"
for l in bistro plume_g-0.9 "$third"; do bash $O/run_study.sh deep "$l" 2>&1 | tee -a "$LOG"; done
for l in bistro plume_g-0.9; do bash $O/run_study.sh denoise "$l" 2>&1 | tee -a "$LOG"; done
bash $O/run_study.sh summary 2>&1 | tee -a "$LOG"
say "phase A done"
