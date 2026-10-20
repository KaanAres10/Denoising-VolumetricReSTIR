#!/bin/bash
# The 17 gallery references re-rendered by the fixed reference renderer (a2a3aa8; paper spec E2): each label's pre-fix
# reference renamed to ref_residual (kept), the new one rendered by run_study.sh refs at 1080p with the old one's
# frames and samples, then ref_change.py. Resumable: a label whose new reference holds its last accumulation is
# skipped; a half-written one is renamed aside (ref_partial_<time>), never deleted. Log: five_refs.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/five_refs.log
LABELS="bunnycathedral_d0.3 bunnyspot bunnysoftbox bunnyinside bunnyback_g0.8 bunnystripes explosion bunnylanterns wdassunset_g0.85 plumeback_g0.9 plumeconcert_g0.6 emeraldnight_d3 explosiondusk_b2 bunnycathedral_d0.3_b2 bunnyback_g0.8_b2 bunnysoftbox_b2 wdassunset_g0.85_b2"
field() { python -c "import json, sys; s = json.load(open(sys.argv[1] + '/c.schedule.json')); print($2)" "$1"; }
finished() { [ -f "$1/c.schedule.json" ] && [ -f "$1/c.Accum.output.$(field "$1" "s['reference_frames'][-1]").exr" ]; }
echo "[$(date +%H:%M:%S)] refs start" >> "$LOG"
for L in $LABELS; do
    d=$O/$L/ref
    old=$O/$L/ref_residual
    if [ ! -d "$old" ]; then
        [ -d "$d" ] || { echo "[$(date +%H:%M:%S)] $L: no reference to keep; abort" >> "$LOG"; exit 1; }
        mv "$d" "$old"
    fi
    if finished "$d"; then echo "[$(date +%H:%M:%S)] $L: kept" >> "$LOG"; continue; fi
    [ -d "$d" ] && mv "$d" "$O/$L/ref_partial_$(date +%Y%m%d%H%M%S)"
    n=$(field "$old" "s['accumulated'][-1]")
    spp=$(field "$old" "s['env'].get('VR_SPP', '16')")
    STUDY_DISPLAY=1920x1080 STUDY_REF_FRAMES="$n" STUDY_REF_SPP="$spp" bash "$O/run_study.sh" refs "$L" >> "$LOG" 2>&1
    finished "$d" || { echo "[$(date +%H:%M:%S)] $L: FAILED, no final accumulation (see $d/run.log)" >> "$LOG"; exit 1; }
done
# shellcheck disable=SC2086
python "$O/ref_change.py" "$O" $LABELS --out "$O/five_denoisers/ref_change.json" >> "$LOG" 2>&1
echo "[$(date +%H:%M:%S)] refs done" >> "$LOG"
