#!/bin/bash
# What the mutations cost (user, 2026-10-06: "evaluate performance"): per-pass GPU time (Falcor's profiler, median over
# the run, correlation_pose.py VR_PASS_TIMES=1) at 1080p, M cap 200, raw estimator (no denoiser: its cost is the same
# with and without mutations), plain vs 1 and 5 mutations (every move kind), at 1 and 2 bounces on the five first-round
# scenes, plus plain with 8 / 16 / 32 initial candidates (shipped 4) to find the equal-time candidate count.
# Stats off (the diagnostic counters and the rebounce check cost time themselves). Needs the GPU to itself.
# Output: outputs/decorr/cost/<label>/<config>/c.passes.json; table: cost_table.py. Log: cost.log.
#   run_cost.sh <label> <k>   only plain with k initial candidates (im<k>; run_equal_time.sh checks its count with it)
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/cost.log
SCRIPT_CP='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
scene_env() { bash -c 'eval "$(sed -n "/^scene_env()/,/^}/p" '"$O"'/run_study.sh)"; scene_env "$1"' _ "$1"; }
cap() {  # label config env...
    local label=$1 cfg=$2; shift 2
    local d="$R/$O/cost/$label/$cfg"
    [ -f "$d/c.passes.json" ] && return 0
    mkdir -p "$d"
    # shellcheck disable=SC2046
    ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
      export $(scene_env "$label") VR_DISPLAY=1920x1080 VR_CHAINS=1 VR_PER_CHAIN=4 VR_SPACING=8 VR_WARM=192 VR_IDS=0 \
             VR_MTHRESH=200 VR_PASS_TIMES=1 "$@"
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 3600 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    echo "[$(date +%H:%M:%S)] cost $label/$cfg: passes.json $([ -f "$d/c.passes.json" ] && echo ok || echo MISSING), $(grep -c '(Error)' "$d/run.log") errors" >> $LOG
}
M="VR_MUTATIONS=5 VR_MUT_STATS=0 VR_MUT_AFTER_SPATIAL=1"
if [ $# -eq 2 ]; then cap "$1" "im$2" VR_INITIAL_M="$2"; exit 0; fi
echo "[$(date +%H:%M:%S)] cost start" >> $LOG
for L in explosiondusk bunnycathedral_d0.3 bunnyback_g0.8 bunnysoftbox wdassunset_g0.85; do
    for B in "$L" "${L}_b2"; do
        S=light,depth,select,flight
        [ "$B" != "$L" ] && S=$S,direction,distance,rebounce
        cap "$B" mut0
        for n in 1 5; do
            # shellcheck disable=SC2086
            cap "$B" mut$n $M VR_MUTATIONS=$n VR_MUT_STRAT=$S
        done
        for k in 8 16 32; do cap "$B" im$k VR_INITIAL_M=$k; done
    done
done
echo "[$(date +%H:%M:%S)] cost done" >> $LOG
