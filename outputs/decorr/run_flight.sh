#!/bin/bash
# The free-flight depth move (MutateSamples strategy "flight", spec V-B10): an independence proposal for the
# scatter depth from the renderer's own distance sampler, where the depth walk is too local to undo the depth
# that reuse copies between pixels. Waits for run_post.sh / run_den2.sh to finish (a build replaces the binary
# and shaders a running study uses), then: build; byte-identity with mutations off; smoke tests on a volume-only
# and a surface scene (frames, accepted proposals, and the pdf evaluator agreeing with the sampler's own density,
# which is how the env re-selection's bias was found); the bias test at low resolution on plume g=-0.9 and
# bistro; then the study on the scenes where the depth is what reuse shares -- the backlit bunny (g=0.8), the
# lamp inside the cloud, plume g=-0.9: M cap 50 with 5 depth, 5 free-flight and 5 moves of all four kinds, then
# all four after spatial reuse at the shipped cap and with the decoupled history. Log: flight.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/flight.log
S="$TEMP/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad"
# FLIGHT_NOWAIT=1: start at once instead of after run_den2.sh (its log line "den2 done").
[ "${FLIGHT_NOWAIT:-0}" = 1 ] || until grep -q "den2 done" $O/select.log; do sleep 120; done
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 60; done
echo "[$(date +%H:%M:%S)] flight start" >> $LOG
FL="VR_MUTATIONS=5 VR_MUT_STRAT=flight VR_MUT_STATS=1"
ALL4="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight VR_MUT_STATS=1"
# FLIGHT_STUDY_ONLY=1: skip the build and the checks (they passed: 9f552f6) and run the study alone.
if [ "${FLIGHT_STUDY_ONLY:-0}" != 1 ]; then
./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target VolumetricReSTIR > "$S/build_flight.log" 2>&1
echo "build $?" | tee -a $LOG
bash outputs/mask_check.sh raw none 2>&1 | tail -1 | tee -a $LOG
SCRIPT_CP=$(cygpath -w "$R/Source/RenderPasses/VolumetricReSTIR/Scripts/correlation_pose.py")
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
fail() { taskkill //IM Mogwai.exe //F > /dev/null 2>&1; echo "[$(date +%H:%M:%S)] flight ABORTED: $1" | tee -a $LOG; exit 1; }
# Smoke: frames, a moving chain, and q's evaluator = the sampler's density (at most 1 in 1000 proposals apart).
for sc in plume bistro; do
    d="$S/smoke_flight_$sc"; mkdir -p "$d"
    ( for v in $(env | grep -o "^VR_[A-Z0-9_]*"); do unset "$v"; done
      VR_SCENE=$sc VR_DISPLAY=480x270 VR_CHAINS=1 VR_PER_CHAIN=2 VR_WARM=280 VR_SPACING=5 VR_MUTATIONS=5 VR_MUT_STRAT=flight VR_MUT_STATS=1 \
          VR_OUT_DIR="$(cygpath -m "$d")" VR_TAG=c timeout 600 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    n=$(ls "$d" | grep -c "accumulated_color.*exr")
    line=$(grep -o "free flight: .*" "$d/run.log" | tail -1)
    echo "smoke $sc: $n frames, $(grep -c '(Error)' "$d/run.log") errors; $line" | tee -a $LOG
    acc=$(echo "$line" | sed -E 's/^free flight: ([0-9]+)\/([0-9]+).*/\1/')
    prop=$(echo "$line" | sed -E 's/^free flight: ([0-9]+)\/([0-9]+).*/\2/')
    mis=$(echo "$line" | sed -E 's/.* ([0-9]+) flight: q evaluator.*/\1/')
    [ "$n" -ge 2 ] || fail "smoke $sc: no frames"
    [ "${acc:-0}" -gt 0 ] 2>/dev/null || fail "smoke $sc: no free-flight move accepted"
    [ "$((mis * 1000))" -le "$prop" ] || fail "smoke $sc: q evaluator disagrees with the sampler ($mis of $prop)"
done
# Bias: the image mean against no reuse, 4 chains x 50 frames, at low resolution.
bias() {
    local L=$1; shift
    local tag=$1; shift
    local d="$S/biasflight/$L/$tag"; mkdir -p "$d"
    ( for v in $(env | grep -o "^VR_[A-Z0-9_]*"); do unset "$v"; done
      env VR_DISPLAY=480x270 VR_CHAINS=4 VR_PER_CHAIN=50 VR_SPACING=2 VR_WARM=256 VR_OUT_DIR="$(cygpath -m "$d")" VR_TAG=c "$@" \
          timeout 2400 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
}
for spec in plume:VR_PHASE_G=-0.9 bistro:; do
    L=${spec%%:*}; G=${spec#*:}
    # shellcheck disable=SC2086
    bias $L noreuse VR_SCENE=$L $G VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
    # shellcheck disable=SC2086
    bias $L cap50 VR_SCENE=$L $G VR_MTHRESH=50
    # shellcheck disable=SC2086
    bias $L cap50_flight VR_SCENE=$L $G VR_MTHRESH=50 $FL
    # shellcheck disable=SC2086
    bias $L cap50_all4_post VR_SCENE=$L $G VR_MTHRESH=50 $ALL4 VR_MUT_AFTER_SPATIAL=1
    python $O/bias_check.py "$S/biasflight/$L" noreuse cap50 cap50_flight cap50_all4_post 2>&1 | sed "s/^/bias $L: /" | tee -a $LOG
done
fi
export STUDY_SPACING=5 STUDY_TIMEOUT=2400
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
DEPTH="VR_MUTATIONS=5 VR_MUT_STRAT=depth VR_MUT_STATS=1"
for L in bunnyback_g0.8 bunnyinside plume_g-0.9; do
    [ "$L" = plume_g-0.9 ] && export STUDY_TIMEOUT=7200
    run $L mcap_50_mut5_depth VR_MTHRESH=50 $DEPTH
    run $L mcap_50_mut5_flight VR_MTHRESH=50 $FL
    run $L mcap_50_mut5_all4 VR_MTHRESH=50 $ALL4
    run $L mut5_all4_post $ALL4 VR_MUT_AFTER_SPATIAL=1
    run $L dec_mcap_200_mut5_all4_post VR_DECOUPLED=1 VR_MTHRESH=200 $ALL4 VR_MUT_AFTER_SPATIAL=1
done
echo "[$(date +%H:%M:%S)] flight done" >> $LOG
