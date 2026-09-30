#!/bin/bash
# Scenes where mutations should have a LARGE effect (spec V-B10). A pixel's estimate is (f/p_hat)(y) runningSum/M
# and a mutation keeps the normalization (V-B7), so the effect is large where the SAMPLE carries the artifact:
#   - the colour the sample chose: 48 coloured lanterns inside the cloud; a warm and a cool emissive panel close
#     to it (which panel: re-selection; where on it: the light-vertex move);
#   - the colour its DEPTH gives: the explosion's self-emission glows at the temperature where the sample sits
#     (white core, red rim), and reuse copies depth between pixels (depth and free-flight moves);
#   - the error a cheap target leaves in f/p_hat: p_hat's transmittance on mip 3 instead of 1 (VR_TARGET_MIP),
#     final shading on mip 0, on the dense bunny (shipped mip 1 alongside);
#   - light through slats (lit slabs along the view ray / stripes across it), the backlit bunny at g = 0.95;
# and the long-history regime (M cap 200 with the spatial output as history), where reuse's blotches are worst
# (Sawhney et al. Fig. 11). Every scene: no reuse, shipped, M cap 50, M cap 200, decoupled M cap 200, each
# without and with 5 moves of all four kinds after spatial reuse. New scenes are smoke-tested first, their
# first frame kept as a PNG. Log: scenes3.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/scenes3.log
S="$TEMP/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad"
SCRIPT_CP=$(cygpath -w "$R/Source/RenderPasses/VolumetricReSTIR/Scripts/correlation_pose.py")
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 60; done
echo "[$(date +%H:%M:%S)] scenes3 start" >> $LOG
NEW=""
for sc in bunnylanterns bunnysoftbox bunnyslabs bunnystripes; do
    d="$S/smoke_$sc"; mkdir -p "$d"
    ( for v in $(env | grep -o "^VR_[A-Z0-9_]*"); do unset "$v"; done
      VR_SCENE=$sc VR_DISPLAY=640x360 VR_CHAINS=1 VR_PER_CHAIN=1 VR_WARM=60 VR_SPACING=5 VR_IDS=1 \
          VR_OUT_DIR="$(cygpath -m "$d")" VR_TAG=c timeout 300 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    if ls "$d" | grep -q "accumulated_color.*exr"; then
        NEW="$NEW $sc"
        python - "$d" <<'PYEOF'
import glob, os, sys
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2, numpy as np
d = sys.argv[1]
img = cv2.imread(sorted(glob.glob(os.path.join(d, "*accumulated_color*.exr")))[0], cv2.IMREAD_UNCHANGED)[..., :3]
k = np.percentile(img, 99.5) + 1e-9
cv2.imwrite(os.path.join(d, "preview.png"), (255 * np.clip(img / k, 0, 1) ** (1 / 2.2)).astype(np.uint8))
PYEOF
        echo "smoke $sc ok: $d/preview.png" | tee -a $LOG
    else
        taskkill //IM Mogwai.exe //F > /dev/null 2>&1; echo "smoke $sc FAILED (see $d/run.log): skipped" | tee -a $LOG
    fi
done
echo "new scenes passing the smoke test:$NEW" | tee -a $LOG
export STUDY_SPACING=5 STUDY_REF_FRAMES=2048 STUDY_TIMEOUT=2400
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
# An old score without the colour metrics is set aside, so the config renders again.
rescore() { local f="$O/$1/$2/c.corr.json"; if [ -f "$f" ] && ! grep -q color_rb "$f"; then mv "$f" "$O/$1/$2/c.corr.v2.json"; fi; }
MALL="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
# matrix <label> [<config prefix> <VAR=value>...]: every configuration, without and with the mutations.
matrix() {
    local L=$1 P=${2:-}; shift; [ $# -gt 0 ] && shift
    for c in noreuse shipped mcap_50 mcap_200 dec_mcap_200; do rescore $L $c; done
    [ -z "$P" ] && run $L noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
    run $L ${P}shipped "$@"
    run $L ${P}mut5_all4_post "$@" $MALL
    run $L ${P}mcap_50 VR_MTHRESH=50 "$@"
    run $L ${P}mcap_50_mut5_all4_post VR_MTHRESH=50 "$@" $MALL
    run $L ${P}mcap_200 VR_MTHRESH=200 "$@"
    run $L ${P}mcap_200_mut5_all4_post VR_MTHRESH=200 "$@" $MALL
    run $L ${P}dec_mcap_200 VR_DECOUPLED=1 VR_MTHRESH=200 "$@"
    run $L ${P}dec_mcap_200_mut5_all4_post VR_DECOUPLED=1 VR_MTHRESH=200 "$@" $MALL
}
passed() { case " $NEW " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
for L in bunnylanterns bunnysoftbox; do
    passed $L || continue
    bash $O/run_study.sh refs $L 2>&1 | tee -a $LOG
    matrix $L
done
export STUDY_TIMEOUT=7200
bash $O/run_study.sh refs explosion 2>&1 | tee -a $LOG  # (skips an existing reference)
matrix explosion
export STUDY_TIMEOUT=2400
matrix bunnyone_d5
matrix bunnyone_d5 tmip3_ VR_TARGET_MIP=3
for L in bunnyslabs bunnystripes; do
    passed $L || continue
    bash $O/run_study.sh refs $L 2>&1 | tee -a $LOG
    matrix $L
done
bash $O/run_study.sh refs bunnyback_g0.95 2>&1 | tee -a $LOG
matrix bunnyback_g0.95
echo "[$(date +%H:%M:%S)] scenes3 done" >> $LOG
