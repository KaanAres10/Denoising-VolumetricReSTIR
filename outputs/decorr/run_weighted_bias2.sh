#!/bin/bash
# A sharper bias test for the weighted point-light proposal (spec V-B10). run_weighted.sh's on the 8-light bunny
# could not resolve less than ~3% (lights inside the cloud: heavy-tailed chains). The 3-light bunny's lights are
# outside the cloud, so its chain means scatter far less. 4 chains x 50 frames at 480x270: no reuse, M cap 50, and
# M cap 50 with 5 re-selections after spatial reuse, uniform vs weighted. Runs once (weighted_bias2.done).
# Log: weighted.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
[ -f $O/weighted_bias2.done ] && exit 0
LOG=$O/weighted.log
S="$TEMP/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad"
SCRIPT_CP=$(cygpath -w "$R/Source/RenderPasses/VolumetricReSTIR/Scripts/correlation_pose.py")
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 30; done
bias() {
    local tag=$1; shift
    local d="$S/biasweighted2/$tag"; mkdir -p "$d"
    ( for v in $(env | grep -o "^VR_[A-Z0-9_]*"); do unset "$v"; done
      env VR_SCENE=bunnyrgb VR_DISPLAY=480x270 VR_CHAINS=4 VR_PER_CHAIN=50 VR_SPACING=2 VR_WARM=256 VR_OUT_DIR="$(cygpath -m "$d")" VR_TAG=c "$@" \
          timeout 2400 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
}
SEL="VR_MUTATIONS=5 VR_MUT_STRAT=select VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
bias noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
bias cap50 VR_MTHRESH=50
# shellcheck disable=SC2086
bias cap50_select_uniform VR_MTHRESH=50 $SEL VR_SELECT_UNIFORM=1
# shellcheck disable=SC2086
bias cap50_select_weighted VR_MTHRESH=50 $SEL
python $O/bias_check.py "$S/biasweighted2" noreuse cap50 cap50_select_uniform cap50_select_weighted 2>&1 | sed "s/^/bias bunnyrgb: /" | tee -a $LOG
for t in cap50_select_uniform cap50_select_weighted; do
    echo "$t: $(grep -o 'light re-selection by kind: .*' "$S/biasweighted2/$t/run.log" | tail -1)" | tee -a $LOG
done
touch $O/weighted_bias2.done
