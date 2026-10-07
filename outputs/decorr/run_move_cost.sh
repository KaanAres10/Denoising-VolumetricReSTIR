#!/bin/bash
# Where Stage 2's mutation time goes (user, 2026-10-07: "can you make it faster still?"): with the move kind drawn once
# per step for the whole frame (the default since this commit), a run that enables one kind alone times that kind.
# Per kind, 1 and 5 mutations (VR_MUT_STRAT=<kind>): one step costs (t5 - t1) / 4, and t1 minus that is the pass's
# fixed part (reading the reservoir, p_hat(x0)). Explosion and panel lights at 1 and 2 bounces, 1080p, M cap 200, stats
# off; a shorter warm-up than run_cost.sh (the pass's cost settles within a few frames). Needs the GPU to itself.
# Output: outputs/decorr/movecost/<label>/<kind>_<n>/c.passes.json; table: move_cost_table.py. Log: movecost.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/movecost.log
SCRIPT_CP='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
scene_env() { bash -c 'eval "$(sed -n "/^scene_env()/,/^}/p" '"$O"'/run_study.sh)"; scene_env "$1"' _ "$1"; }
cap() {  # label kind n
    local label=$1 kind=$2 n=$3
    local d="$R/$O/movecost/$label/${kind}_$n"
    [ -f "$d/c.passes.json" ] && return 0
    mkdir -p "$d"
    # shellcheck disable=SC2046
    ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
      export $(scene_env "$label") VR_DISPLAY=1920x1080 VR_CHAINS=1 VR_PER_CHAIN=4 VR_SPACING=8 VR_WARM=64 VR_IDS=0 \
             VR_MTHRESH=200 VR_PASS_TIMES=1 VR_MUTATIONS=$n VR_MUT_STATS=0 VR_MUT_AFTER_SPATIAL=1 VR_MUT_STRAT=$kind
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 1200 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    echo "[$(date +%H:%M:%S)] movecost $label/${kind}_$n: passes.json $([ -f "$d/c.passes.json" ] && echo ok || echo MISSING), $(grep -c '(Error)' "$d/run.log") errors" >> $LOG
}
echo "[$(date +%H:%M:%S)] movecost start" >> $LOG
for L in explosiondusk bunnysoftbox explosiondusk_b2 bunnysoftbox_b2; do
    K="light depth select flight"
    case $L in *_b2) K="$K direction distance rebounce" ;; esac
    for k in $K; do
        cap "$L" "$k" 1
        cap "$L" "$k" 5
    done
done
echo "[$(date +%H:%M:%S)] movecost done" >> $LOG
