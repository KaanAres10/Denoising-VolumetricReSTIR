#!/bin/bash
# The light re-selection's position-aware point-light proposal (spec V-B10): a point light by its unshadowed
# contribution at the scatter point instead of uniformly -- among 48 lanterns the uniform one was accepted 6% of the
# time. Waits for run_scenes3.sh's colour stage (a build replaces the binary and shaders a running study uses), then:
# build; byte-identity with mutations off; smoke on the lanterns (re-selection must be accepted, the per-kind rates
# logged); bias on the 8-light bunny at low resolution, weighted vs uniform (VR_SELECT_UNIFORM=1); the lanterns'
# mutation configs again with the new proposal (…all4w…, beside the uniform …all4…). Log: weighted.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/weighted.log
S="$TEMP/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad"
until grep -q "scenes3 colour done" $O/scenes3.log; do sleep 60; done
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 30; done
echo "[$(date +%H:%M:%S)] weighted start" >> $LOG
./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target VolumetricReSTIR > "$S/build_weighted.log" 2>&1
echo "build $?" | tee -a $LOG
bash outputs/mask_check.sh raw none 2>&1 | tail -1 | tee -a $LOG
SCRIPT_CP=$(cygpath -w "$R/Source/RenderPasses/VolumetricReSTIR/Scripts/correlation_pose.py")
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
fail() { taskkill //IM Mogwai.exe //F > /dev/null 2>&1; echo "[$(date +%H:%M:%S)] weighted ABORTED: $1" | tee -a $LOG; exit 1; }
d="$S/smoke_weighted"; mkdir -p "$d"
( for v in $(env | grep -o "^VR_[A-Z0-9_]*"); do unset "$v"; done
  VR_SCENE=bunnylanterns VR_DISPLAY=480x270 VR_CHAINS=1 VR_PER_CHAIN=2 VR_WARM=280 VR_SPACING=5 VR_MUTATIONS=5 VR_MUT_STRAT=select VR_MUT_STATS=1 \
      VR_OUT_DIR="$(cygpath -m "$d")" VR_TAG=c timeout 600 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
n=$(ls "$d" | grep -c "accumulated_color.*exr")
line=$(grep -o "light re-selection by kind: .*" "$d/run.log" | tail -1)
echo "smoke lanterns: $n frames, $(grep -c '(Error)' "$d/run.log") errors; $line" | tee -a $LOG
acc=$(echo "$line" | sed -E 's/.*analytic ([0-9]+)\/.*/\1/')
[ "$n" -ge 2 ] || fail "smoke: no frames"
[ "${acc:-0}" -gt 0 ] 2>/dev/null || fail "smoke: no analytic re-selection accepted"
bias() {
    local tag=$1; shift
    local d="$S/biasweighted/$tag"; mkdir -p "$d"
    ( for v in $(env | grep -o "^VR_[A-Z0-9_]*"); do unset "$v"; done
      env VR_SCENE=bunnyparty VR_DISPLAY=480x270 VR_CHAINS=4 VR_PER_CHAIN=50 VR_SPACING=2 VR_WARM=256 VR_OUT_DIR="$(cygpath -m "$d")" VR_TAG=c "$@" \
          timeout 2400 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
}
SEL="VR_MUTATIONS=5 VR_MUT_STRAT=select VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
# shellcheck disable=SC2086
bias noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
# shellcheck disable=SC2086
bias cap50 VR_MTHRESH=50
# shellcheck disable=SC2086
bias cap50_select_uniform VR_MTHRESH=50 $SEL VR_SELECT_UNIFORM=1
# shellcheck disable=SC2086
bias cap50_select_weighted VR_MTHRESH=50 $SEL
python $O/bias_check.py "$S/biasweighted" noreuse cap50 cap50_select_uniform cap50_select_weighted 2>&1 | sed "s/^/bias bunnyparty: /" | tee -a $LOG
for t in cap50_select_uniform cap50_select_weighted; do
    echo "$t: $(grep -o 'light re-selection by kind: .*' "$S/biasweighted/$t/run.log" | tail -1)" | tee -a $LOG
done
export STUDY_SPACING=5 STUDY_TIMEOUT=2400
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
MALL="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
run bunnylanterns mut5_all4w_post $MALL
run bunnylanterns mcap_50_mut5_all4w_post VR_MTHRESH=50 $MALL
run bunnylanterns mcap_200_mut5_all4w_post VR_MTHRESH=200 $MALL
run bunnylanterns dec_mcap_200_mut5_all4w_post VR_DECOUPLED=1 VR_MTHRESH=200 $MALL
echo "[$(date +%H:%M:%S)] weighted done" >> $LOG
