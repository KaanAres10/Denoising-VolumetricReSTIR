#!/bin/bash
# One Mogwai capture for the paper's runs (docs/superpowers/specs/2026-10-20-mutation-paper-design.md):
#   five_capture.sh <run dir> [VAR=value ...]
# runs FIVE_SCRIPT (default correlation_pose.py, in the Scripts directory) into <run dir> (tag c, run.log beside
# it) with the VR_/NRD4_/LANTERN_ environment cleared and the given assignments set, and Mogwai's stdin closed (a
# caller's `while read` loop keeps its input). Waits up to a minute for an earlier Mogwai to exit (one at a time):
# exit 3 if one is still running, else Mogwai's status (124 = FIVE_TIMEOUT seconds, default 3600; 143 = stopped
# because the log showed a Falcor "(Error)" or "(Fatal)"). FIVE_MOGWAI replaces Mogwai.exe (the tests' stand-in).
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
d=$1
shift
for _ in $(seq 1 60); do tasklist 2>/dev/null | grep -qi mogwai || break; sleep 1; done
if tasklist 2>/dev/null | grep -qi mogwai; then echo "five_capture: a Mogwai is running; not starting" >&2; exit 3; fi
mkdir -p "$d"
script='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\'"${FIVE_SCRIPT:-correlation_pose.py}"
(
    for v in $(env | grep -o "^\(VR_\|NRD4_\|LANTERN_\)[A-Z0-9_]*"); do unset "$v"; done
    export MSYS_NO_PATHCONV=1 "$@"
    : > "$d/run.log"  # an earlier attempt's log, before Mogwai's own redirect empties it, would trip the watch below
    VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout "${FIVE_TIMEOUT:-3600}" "${FIVE_MOGWAI:-./build/windows-vs2022/bin/Release/Mogwai.exe}" \
        --script "$script" > "$d/run.log" 2>&1 < /dev/null &
    pid=$!
    # A script that fails leaves Mogwai open until the timeout, and any "(Error)" already fails the run
    # (five_runs.py --complete), so stop it as soon as one is logged; likewise a "(Fatal)" (a GPU fault: Mogwai
    # reports the failed present and sits).
    while kill -0 "$pid" 2>/dev/null; do
        if grep -q -E "\(Error\)|\(Fatal\)" "$d/run.log" 2>/dev/null; then kill "$pid"; break; fi
        sleep 2
    done
    wait "$pid"
)
