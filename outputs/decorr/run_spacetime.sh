#!/bin/bash
# The space-time strips (spacetime_runs.py): each replay captured by five_capture.sh into outputs/decorr/<label>/<config>,
# one Mogwai at a time. A finished replay (spacetime_runs.py --complete) is kept, so a cut-off queue resumes; a failed one
# is logged and the queue goes on. Starts only with 10 GB free on C:. Log: outputs/decorr/spacetime.log.
# bash run_spacetime.sh [--night]: --night replays the night street's M cap 50 runs (spacetime_runs.py --night).
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/spacetime.log
free=$(df -BG --output=avail /c | tail -1 | tr -dc 0-9)
if [ "$free" -lt 10 ]; then echo "[$(date +%H:%M:%S)] spacetime: only ${free} GB free on C:" | tee -a "$LOG"; exit 1; fi
echo "[$(date +%H:%M:%S)] spacetime start, ${free} GB free" >> "$LOG"
PLAN=$O/spacetime_planned.txt
[ "${1:-}" = --night ] && PLAN=$O/spacetime_planned_night.txt
python "$O/spacetime_runs.py" --list "$@" > "$PLAN" || exit 1
while read -r label cfg env; do
    d=$O/$label/$cfg
    if python "$O/spacetime_runs.py" --complete "$d"; then echo "[$(date +%H:%M:%S)] $label/$cfg kept" >> "$LOG"; continue; fi
    t0=$SECONDS
    # shellcheck disable=SC2086
    FIVE_TIMEOUT=1800 bash "$O/five_capture.sh" "$d" $env
    if python "$O/spacetime_runs.py" --complete "$d"; then
        echo "[$(date +%H:%M:%S)] $label/$cfg done $((SECONDS - t0))s" >> "$LOG"
    else
        echo "[$(date +%H:%M:%S)] $label/$cfg FAILED (see $d/run.log)" >> "$LOG"
    fi
done < "$PLAN"
echo "[$(date +%H:%M:%S)] spacetime done, $(df -BG --output=avail /c | tail -1 | tr -dc 0-9) GB free" >> "$LOG"
