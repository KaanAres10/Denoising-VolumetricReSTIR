#!/bin/bash
# Scenes where mutations should have a LARGE effect (spec V-B10). A pixel's estimate is (f/p_hat)(y) runningSum/M
# and a mutation keeps the normalization (V-B7), so the effect is large where the SAMPLE carries the artifact:
#   colour  the colour the sample chose: 48 coloured lanterns inside the cloud; a warm and a cool emissive panel
#           beside it (which panel: re-selection; where on it: the light-vertex move);
#   film    film-style shots: concert beams through stage smoke (g 0.6), god rays through a stone hall's windows
#           (dust thinned to 0.3x), the Disney cloud backlit at sunset (g 0.85), Emerald Square at night in thick
#           fog lit by its street lamps (fog 3x);
#   rest    the colour the sample's DEPTH gives (the explosion's self-emission glows at the temperature where the
#           sample sits, and reuse copies depth between pixels); the error a cheap target leaves in f/p_hat
#           (p_hat's transmittance on mip 3 instead of 1, VR_TARGET_MIP, on the dense bunny); light through slats
#           (lit slabs along the view ray / stripes across it); the backlit bunny at g = 0.95.
# Each in the long-history regime too (M cap 200 with the spatial output as history, Sawhney et al. Fig. 11).
# Every scene: no reuse, shipped, M cap 50, M cap 200, decoupled M cap 200, each without and with 5 moves of all
# four kinds after spatial reuse (Emerald: no M cap 200 pair, for time). New scenes are smoke-tested first, their
# first frame kept as preview.png with the lit fraction logged.
#   run_scenes3.sh [preview|colour|film|rest|all]      Log: scenes3.log.
set -u
STAGE=${1:-all}
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/scenes3.log
S="$TEMP/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad"
SCRIPT_CP=$(cygpath -w "$R/Source/RenderPasses/VolumetricReSTIR/Scripts/correlation_pose.py")
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 60; done
echo "[$(date +%H:%M:%S)] scenes3 $STAGE start" >> $LOG
NEW=""
smoke() {
    local sc d
    for sc in "$@"; do
        d="$S/smoke_$sc"; mkdir -p "$d"
        ( for v in $(env | grep -o "^VR_[A-Z0-9_]*"); do unset "$v"; done
          VR_SCENE=$sc VR_DISPLAY=640x360 VR_CHAINS=1 VR_PER_CHAIN=1 VR_WARM=60 VR_SPACING=5 VR_IDS=1 \
              VR_OUT_DIR="$(cygpath -m "$d")" VR_TAG=c timeout 400 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
        if ls "$d" | grep -q "accumulated_color.*exr"; then
            NEW="$NEW $sc"
            lit=$(python - "$d" <<'PYEOF'
import glob, os, sys
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2, numpy as np
d = sys.argv[1]
img = cv2.imread(sorted(glob.glob(os.path.join(d, "*accumulated_color*.exr")))[0], cv2.IMREAD_UNCHANGED)[..., :3]
img = np.nan_to_num(img, posinf=0.0)
k = np.percentile(img, 99.5) + 1e-9
cv2.imwrite(os.path.join(d, "preview.png"), (255 * np.clip(img / k, 0, 1) ** (1 / 2.2)).astype(np.uint8))
lum = img @ np.array([0.0722, 0.7152, 0.2126])
print("%.3f" % float((lum > 0.05 * np.percentile(lum, 99.5)).mean()))
PYEOF
)
            echo "smoke $sc ok, lit fraction ${lit:-?}: $d/preview.png" | tee -a $LOG
        else
            taskkill //IM Mogwai.exe //F > /dev/null 2>&1; echo "smoke $sc FAILED (see $d/run.log): skipped" | tee -a $LOG
        fi
    done
}
passed() { case " $NEW " in *" ${1%%_*} "*) return 0 ;; *) return 1 ;; esac; }
export STUDY_SPACING=5 STUDY_SPACING_emeraldnight_d3=3 STUDY_REF_FRAMES=2048 STUDY_TIMEOUT=2400
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
# An old score without the colour metrics is set aside, so the config renders again.
rescore() { local f="$O/$1/$2/c.corr.json"; if [ -f "$f" ] && ! grep -q color_rb "$f"; then mv "$f" "$O/$1/$2/c.corr.v2.json"; fi; }
MALL="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
# matrix <label> [<config prefix> <VAR=value>...]: every configuration, without and with the mutations.
# MATRIX_NO_CAP200=1 leaves out the M cap 200 pair.
matrix() {
    local L=$1 P=${2:-}; shift; [ $# -gt 0 ] && shift
    for c in noreuse shipped mcap_50 mcap_200 dec_mcap_200; do rescore $L $c; done
    [ -z "$P" ] && run $L noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
    run $L ${P}shipped "$@"
    run $L ${P}mut5_all4_post "$@" $MALL
    run $L ${P}mcap_50 VR_MTHRESH=50 "$@"
    run $L ${P}mcap_50_mut5_all4_post VR_MTHRESH=50 "$@" $MALL
    if [ "${MATRIX_NO_CAP200:-0}" != 1 ]; then
        run $L ${P}mcap_200 VR_MTHRESH=200 "$@"
        run $L ${P}mcap_200_mut5_all4_post VR_MTHRESH=200 "$@" $MALL
    fi
    run $L ${P}dec_mcap_200 VR_DECOUPLED=1 VR_MTHRESH=200 "$@"
    run $L ${P}dec_mcap_200_mut5_all4_post VR_DECOUPLED=1 VR_MTHRESH=200 "$@" $MALL
}
scene() {  # a new scene: its reference, then the matrix, if it passed the smoke test
    passed $1 || return 0
    bash $O/run_study.sh refs $1 2>&1 | tee -a $LOG
    matrix $1
}
case $STAGE in preview)  # smoke tests (with previews) alone, to check a new scene's framing and lighting early
    smoke plumeconcert bunnycathedral wdassunset emeraldnight ;;
esac
case $STAGE in colour|all)
    smoke bunnylanterns bunnysoftbox
    scene bunnylanterns
    scene bunnysoftbox ;;
esac
case $STAGE in film|all)
    # The weighted point-light proposal's sharper bias test first (once): the film shots use the proposal.
    bash $O/run_weighted_bias2.sh
    smoke plumeconcert bunnycathedral wdassunset emeraldnight
    scene plumeconcert_g0.6
    scene bunnycathedral_d0.3
    export STUDY_TIMEOUT=7200
    scene wdassunset_g0.85
    MATRIX_NO_CAP200=1 scene emeraldnight_d3
    export STUDY_TIMEOUT=2400 ;;
esac
case $STAGE in rest|all)
    smoke bunnyslabs bunnystripes
    export STUDY_TIMEOUT=7200
    bash $O/run_study.sh refs explosion 2>&1 | tee -a $LOG  # (skips an existing reference)
    matrix explosion
    export STUDY_TIMEOUT=2400
    matrix bunnyone_d5
    matrix bunnyone_d5 tmip3_ VR_TARGET_MIP=3
    scene bunnyslabs
    scene bunnystripes
    bash $O/run_study.sh refs bunnyback_g0.95 2>&1 | tee -a $LOG
    matrix bunnyback_g0.95 ;;
esac
echo "[$(date +%H:%M:%S)] scenes3 $STAGE done" >> $LOG
