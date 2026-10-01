#!/bin/bash
# A bias test that can resolve the weighted point-light proposal (spec V-B10). The bunny tests could not: a point
# light inside a medium makes the estimate heavy-tailed (the variance integral of 1/r^4 diverges near the light), and
# at M cap 50 four chains are few independent samples. Here: the concert -- six spotlights OUTSIDE the plume, whose
# smooth medium resolved ~0.02% before -- at the shipped cap (short correlation time), 16 chains x 12 frames at
# 480x270: no reuse, shipped, and shipped with 5 re-selections after spatial reuse, uniform vs weighted. Once
# (weighted_bias3.done). Log: weighted.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
[ -f $O/weighted_bias3.done ] && exit 0
LOG=$O/weighted.log
S="$TEMP/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad"
SCRIPT_CP=$(cygpath -w "$R/Source/RenderPasses/VolumetricReSTIR/Scripts/correlation_pose.py")
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 30; done
bias() {
    local tag=$1; shift
    local d="$S/biasweighted3/$tag"; mkdir -p "$d"
    ( for v in $(env | grep -o "^VR_[A-Z0-9_]*"); do unset "$v"; done
      env VR_SCENE=plumeconcert VR_PHASE_G=0.6 VR_DISPLAY=480x270 VR_CHAINS=16 VR_PER_CHAIN=12 VR_SPACING=4 VR_WARM=128 \
          VR_OUT_DIR="$(cygpath -m "$d")" VR_TAG=c "$@" timeout 2400 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
}
SEL="VR_MUTATIONS=5 VR_MUT_STRAT=select VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
bias noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
bias shipped
# shellcheck disable=SC2086
bias select_uniform $SEL VR_SELECT_UNIFORM=1
# shellcheck disable=SC2086
bias select_weighted $SEL
python $O/bias_check.py "$S/biasweighted3" noreuse shipped select_uniform select_weighted 2>&1 | sed "s/^/bias plumeconcert: /" | tee -a $LOG
for t in select_uniform select_weighted; do
    echo "$t: $(grep -o 'light re-selection by kind: .*' "$S/biasweighted3/$t/run.log" | tail -1)" | tee -a $LOG
done
touch $O/weighted_bias3.done
