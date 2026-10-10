#!/bin/bash
# Scenes where ONE mutation per frame should not be enough (spec V-C7; user, 2026-10-10: "create scenes such that
# multiple mutations are required to get rid of significant artifacts"). Judged mainly at M cap 200, where reuse's
# blotches are big enough for the count to matter. The pass as shipped (coherent moves, early rejection, moves after
# spatial reuse, every kind), 960x540, run_study.sh's capture and scoring (m_corr.py, 100 frames per config).
#   smoke    each new scene once at 640x360: preview.png and the lit fraction (counts_smoke/<label>/)
#   pilot    no reuse, and 0 / 1 / 5 / 20 mutations at M cap 200 (5 with acceptance statistics)
#   fill     2 / 3 / 10 mutations at M cap 200
#   ship     0 / 1 / 5 mutations at the shipped M cap
# then count_curve.py's table (counts.log, counts_summary.json). A config already scored is skipped (run_study.sh),
# so a cut-off queue resumes where it stopped.
#   run_counts.sh [smoke|pilot|fill|ship|all]      Log: counts.log.
set -u
STAGE=${1:-all}
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/counts.log
SCRIPT_CP=$(cygpath -w "$R/Source/RenderPasses/VolumetricReSTIR/Scripts/correlation_pose.py")
LABELS="bunnyswarm_d3 bunnybeam bunnypinback_g0.97 bunnypinback_g0.97_b2 bunnyclosebox_b2"
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 60; done
scene_env() { bash -c 'eval "$(sed -n "/^scene_env()/,/^}/p" '"$O"'/run_study.sh)"; scene_env "$1"' _ "$1"; }
echo "[$(date +%H:%M:%S)] counts $STAGE start" >> $LOG
export STUDY_DISPLAY=960x540 STUDY_SPACING=5 STUDY_TIMEOUT=7200
strat() { case $1 in *_b2) echo light,depth,select,flight,direction,distance,rebounce ;; *) echo light,depth,select,flight ;; esac; }
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
muts() {  # label config-prefix count [VAR=value...]
    local L=$1 P=$2 N=$3
    shift 3
    if [ "$N" = 0 ]; then run "$L" "${P}_m0" "$@"
    else
        local stats=""
        [ "$N" = 5 ] && stats="VR_MUT_STATS=1"
        # shellcheck disable=SC2086
        run "$L" "${P}_m$N" "$@" VR_MUTATIONS="$N" VR_MUT_STRAT="$(strat "$L")" VR_MUT_AFTER_SPATIAL=1 $stats
    fi
}
smoke() {
    local L d
    for L in $LABELS; do
        d="$R/$O/counts_smoke/$L"
        [ -f "$d/preview.png" ] && continue
        mkdir -p "$d"
        # shellcheck disable=SC2046
        ( for v in $(env | grep -o "^VR_[A-Z0-9_]*"); do unset "$v"; done
          export $(scene_env "$L") VR_DISPLAY=640x360 VR_CHAINS=1 VR_PER_CHAIN=1 VR_WARM=60 VR_SPACING=5 VR_IDS=1
          VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 600 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
        if ls "$d" | grep -q "accumulated_color.*exr"; then
            python "$O/smoke_preview.py" "$d" | sed "s|^|smoke $L ok: |" | tee -a $LOG
        else
            taskkill //IM Mogwai.exe //F > /dev/null 2>&1; echo "smoke $L FAILED (see $d/run.log)" | tee -a $LOG
        fi
    done
}
ok() { [ -f "$R/$O/counts_smoke/$1/preview.png" ]; }
case $STAGE in smoke|all) smoke ;; esac
case $STAGE in pilot|all)
    for L in $LABELS; do ok "$L" || continue
        run "$L" noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
        for N in 0 1 5 20; do muts "$L" c200 "$N" VR_MTHRESH=200; done
    done ;;
esac
case $STAGE in fill|all)
    for L in $LABELS; do ok "$L" || continue
        for N in 2 3 10; do muts "$L" c200 "$N" VR_MTHRESH=200; done
    done ;;
esac
case $STAGE in ship|all)
    for L in $LABELS; do ok "$L" || continue
        for N in 0 1 5; do muts "$L" ship "$N"; done
    done ;;
esac
# shellcheck disable=SC2086
python $O/count_curve.py $O $LABELS --json $O/counts_summary.json 2>&1 | tee -a $LOG
echo "[$(date +%H:%M:%S)] counts $STAGE done" >> $LOG
