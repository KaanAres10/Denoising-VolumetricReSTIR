#!/bin/bash
# The paper's five-denoiser runs (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E3): five_runs.py's
# list in order (M cap 200 first), each captured by five_capture.sh into outputs/decorr/<label>/<config>. A run that
# finished (five_runs.py --complete) is kept, so a cut-off queue resumes; a failed one is logged and the queue goes
# on. Starts only with FIVE_MIN_FREE_GB (35) free on C:. FIVE_SETS splits the shared graph (gate 3).
# Log: outputs/decorr/five.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/five.log
mkdir -p "$O/five_denoisers"
free=$(df -BG --output=avail /c | tail -1 | tr -dc 0-9)
if [ "$free" -lt "${FIVE_MIN_FREE_GB:-35}" ]; then
    echo "[$(date +%H:%M:%S)] five: only ${free} GB free on C:, need ${FIVE_MIN_FREE_GB:-35}" | tee -a "$LOG"
    exit 1
fi
echo "[$(date +%H:%M:%S)] five start, ${free} GB free" >> "$LOG"
python "$O/five_runs.py" --list --sets "${FIVE_SETS:-optix,oidn,relax,reblur}" > "$O/five_denoisers/planned.txt" || exit 1
while read -r label cfg n env; do
    d=$O/$label/$cfg
    if python "$O/five_runs.py" --complete "$d" "$n"; then echo "[$(date +%H:%M:%S)] $label/$cfg kept" >> "$LOG"; continue; fi
    t0=$SECONDS
    # shellcheck disable=SC2086
    bash "$O/five_capture.sh" "$d" $env
    if python "$O/five_runs.py" --complete "$d" "$n"; then
        echo "[$(date +%H:%M:%S)] $label/$cfg done $((SECONDS - t0))s" >> "$LOG"
    else
        echo "[$(date +%H:%M:%S)] $label/$cfg FAILED: $(ls "$d"/c.*.exr 2>/dev/null | wc -l) of $n captures (see $d/run.log)" >> "$LOG"
    fi
done < "$O/five_denoisers/planned.txt"
echo "[$(date +%H:%M:%S)] five done, $(df -BG --output=avail /c | tail -1 | tr -dc 0-9) GB free" >> "$LOG"
