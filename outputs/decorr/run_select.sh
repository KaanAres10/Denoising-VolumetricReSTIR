#!/bin/bash
# The light re-selection move (MutateSamples strategy "select", spec V-B9) against the colour artifacts it is
# built for, after the stress survey: build, byte-identity with the move off, then on every scene with more
# than one light to choose from (bunnyrgb, emerald, bistro) and on env-lit plume g=-0.9 (re-selection there
# redraws the sky direction): shipped / M cap 50 / decoupled M cap 200, each with and without 5 re-selection
# moves. Baselines scored before the colour metrics are re-rendered (their old score kept as c.corr.v2.json).
# Between the bunnyrgb and the emerald/bistro matrices, the new stress scenes (lamp inside the cloud,
# spotlight beam, eight coloured lights, backlit plume; forward-scattering variants), each smoke-tested first.
# Log: select.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/select.log
S="$TEMP/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad"
export STUDY_SPACING=5 STUDY_SPACING_emerald=3 STUDY_TIMEOUT=7200
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
# An old score without the colour metrics is set aside, so the config renders again.
rescore() { local f="$O/$1/$2/c.corr.json"; if [ -f "$f" ] && ! grep -q color_rb "$f"; then mv "$f" "$O/$1/$2/c.corr.v2.json"; fi; }
echo "[$(date +%H:%M:%S)] select start" >> $LOG
./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target VolumetricReSTIR > "$S/build_select.log" 2>&1
echo "build $?" | tee -a $LOG
bash outputs/mask_check.sh raw none 2>&1 | tail -1 | tee -a $LOG
# Smoke test: a shader error would otherwise hold every run below on Falcor's error dialog until the timeout.
SCRIPT_CP=$(cygpath -w "$R/Source/RenderPasses/VolumetricReSTIR/Scripts/correlation_pose.py")
mkdir -p "$S/smoke_select"
( for v in $(env | grep -o "^VR_[A-Z0-9_]*"); do unset "$v"; done
  VR_SCENE=bunnyrgb VR_DISPLAY=480x270 VR_CHAINS=1 VR_PER_CHAIN=2 VR_WARM=280 VR_SPACING=5 VR_MUTATIONS=5 VR_MUT_STRAT=select VR_MUT_STATS=1 VR_OUT_DIR="$(cygpath -m "$S/smoke_select")" VR_TAG=c timeout 300 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "$SCRIPT_CP" > "$S/smoke_select/run.log" 2>&1 )
n=$(ls "$S/smoke_select" | grep -c "accumulated_color.*exr")
echo "smoke select: $n frames, $(grep -c '(Error)' "$S/smoke_select/run.log") errors" | tee -a $LOG
# ...and the move must actually move: a proposal bug once rejected all of 50M proposals without an error.
acc=$(grep -o "light re-selection [0-9]*/[0-9]* accepted" "$S/smoke_select/run.log" | tail -1 | grep -o "[0-9]*/" | tr -d /)
echo "smoke select: re-selections accepted ${acc:-none}" | tee -a $LOG
if [ "$n" -lt 2 ] || [ "${acc:-0}" -eq 0 ]; then taskkill //IM Mogwai.exe //F > /dev/null 2>&1; echo "[$(date +%H:%M:%S)] select ABORTED: smoke test failed" >> $LOG; exit 1; fi
M5="VR_MUTATIONS=5 VR_MUT_STRAT=select VR_MUT_STATS=1"
MALL="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select VR_MUT_STATS=1"
select_matrix() {
    local L=$1
    for c in noreuse shipped mcap_50 dec_mcap_200; do rescore $L $c; done
    run $L noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
    run $L shipped
    run $L mut5_select $M5
    run $L mcap_50 VR_MTHRESH=50
    run $L mcap_50_mut5_select VR_MTHRESH=50 $M5
    run $L dec_mcap_200 VR_DECOUPLED=1 VR_MTHRESH=200
    run $L dec_mcap_200_mut5_select VR_DECOUPLED=1 VR_MTHRESH=200 $M5
}
select_matrix bunnyrgb
# New stress scenes (the user: scenes that make artifacts mutations can handle): a lamp inside the cloud, a
# spotlight beam through it, eight coloured lights, the plume backlit; forward-scattering variants. Every
# mutation config uses all three strategies (light, depth, select).
export STUDY_REF_FRAMES=2048 STUDY_TIMEOUT=2400
# Smoke each new scene first: a broken .pyscene would hold a run on Falcor's error dialog until the timeout.
NEW=""
for sc in bunnyinside bunnyspot bunnyparty plumeback; do
    d="$S/smoke_$sc"; mkdir -p "$d"
    ( for v in $(env | grep -o "^VR_[A-Z0-9_]*"); do unset "$v"; done
      VR_SCENE=$sc VR_DISPLAY=640x360 VR_CHAINS=1 VR_PER_CHAIN=1 VR_WARM=60 VR_SPACING=5 VR_IDS=1       VR_OUT_DIR="$(cygpath -m "$d")" VR_TAG=c timeout 180 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    if ls "$d" | grep -q "accumulated_color.*exr"; then NEW="$NEW $sc"; else
        taskkill //IM Mogwai.exe //F > /dev/null 2>&1; echo "smoke $sc FAILED (see $d/run.log): skipped" | tee -a $LOG; fi
done
echo "new scenes passing the smoke test:$NEW" | tee -a $LOG
for L in bunnyinside bunnyinside_g0.8 bunnyspot bunnyspot_g0.8 bunnyparty plumeback_g0.9; do
    case " $NEW " in *" ${L%%_*} "*) ;; *) continue ;; esac
    bash $O/run_study.sh refs $L 2>&1 | tee -a $LOG
    run $L noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
    run $L shipped
    run $L mut5_all $MALL
    run $L mcap_50 VR_MTHRESH=50
    run $L mcap_50_mut5_all VR_MTHRESH=50 $MALL
    run $L dec_mcap_200 VR_DECOUPLED=1 VR_MTHRESH=200
    run $L dec_mcap_200_mut5_all VR_DECOUPLED=1 VR_MTHRESH=200 $MALL
done
export STUDY_TIMEOUT=7200
for L in plume_g-0.9 emerald bistro; do select_matrix $L; done
echo "[$(date +%H:%M:%S)] select done" >> $LOG
