#!/bin/bash
# The mutation speed-up's A/B (user, 2026-10-06: "make it faster while keeping visual quality same"): two versions of
# MutateSamples.cs.slang in the same binary -- the runtime copy (bin/.../shaders) is swapped between runs -- in the
# order A B B A per scene setup, so GPU heat drifts out of the difference. Per run: GPU pass times (VR_PASS_TIMES) and
# the 4 captured frames, which speed_ab_check.py compares bit for bit (A1 vs A2 first: the renderer must repeat
# itself). 1080p, M cap 200, 5 mutations of every kind, stats off -- run_cost.sh's mut5. Needs the GPU to itself.
#
#   run_speed_ab.sh <name> <A shader> <B shader> [extra env for B...]
#
# Output: outputs/decorr/speed_ab/<name>/<label>/{A1,B1,B2,A2}/; log: speed_ab.log. The bin copy is left as B (the
# version just built) on exit.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/speed_ab.log
NAME=$1 A=$2 B=$3
shift 3
BENV=("$@")
# SPEED_AB_AENV="VAR=value ...": extra env for the A runs (e.g. a switch's off side when B is the default).
read -r -a AENV <<< "${SPEED_AB_AENV:-}"
SCRIPT_CP='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
BIN_SHADER=build/windows-vs2022/bin/Release/shaders/RenderPasses/VolumetricReSTIR/MutateSamples.cs.slang
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
[ -f "$A" ] && [ -f "$B" ] || { echo "missing shader: $A or $B"; exit 1; }
trap 'cp "$B" "$BIN_SHADER"' EXIT
scene_env() { bash -c 'eval "$(sed -n "/^scene_env()/,/^}/p" '"$O"'/run_study.sh)"; scene_env "$1"' _ "$1"; }
run() {  # label variant (A1 B1 B2 A2) strategies
    local label=$1 v=$2 strat=$3
    local d="$R/$O/speed_ab/$NAME/$label/$v"
    [ -f "$d/c.passes.json" ] && return 0
    mkdir -p "$d"
    local extra=()
    case $v in A*) cp "$A" "$BIN_SHADER"; extra=("${AENV[@]}") ;; B*) cp "$B" "$BIN_SHADER"; extra=("${BENV[@]}") ;; esac
    # shellcheck disable=SC2046
    ( for x in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$x"; done
      export $(scene_env "$label") VR_DISPLAY=1920x1080 VR_CHAINS=1 VR_PER_CHAIN=4 VR_SPACING=8 VR_WARM=192 VR_IDS=0 \
             VR_MTHRESH=200 VR_PASS_TIMES=1 VR_MUTATIONS=5 VR_MUT_STATS=0 VR_MUT_AFTER_SPATIAL=1 VR_MUT_STRAT="$strat" \
             "${extra[@]}"
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 1200 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    echo "[$(date +%H:%M:%S)] ab $NAME $label/$v: passes.json $([ -f "$d/c.passes.json" ] && echo ok || echo MISSING), $(ls "$d"/*.exr 2>/dev/null | wc -l) exr, $(grep -c '(Error)' "$d/run.log") errors" >> $LOG
}
echo "[$(date +%H:%M:%S)] ab $NAME start: A=$A ${AENV[*]} B=$B ${BENV[*]}" >> $LOG
for L in explosiondusk bunnycathedral_d0.3 bunnyback_g0.8 bunnysoftbox wdassunset_g0.85; do
    for X in "$L" "${L}_b2"; do
        S=light,depth,select,flight
        [ "$X" != "$L" ] && S=$S,direction,distance,rebounce
        for v in A1 B1 B2 A2; do run "$X" $v "$S"; done
    done
done
echo "[$(date +%H:%M:%S)] ab $NAME done" >> $LOG
python $O/speed_ab_check.py $O/speed_ab/$NAME 2>&1 | tee -a $LOG
