#!/bin/bash
# Are the bounce moves at a SURFACE first vertex unbiased? (user, 2026-10-19: "yes" to moves for paths that hit a
# surface first -- the wet ground's glow reflections, which no move reached.) run_bias_final.sh's protocol on the wet
# ground (lanternglow at night over a dark glossy ground, 2 bounces): plain ReSTIR vs 5 mutations of all seven kinds
# after spatial reuse, M cap 200 (the long history: the moves do the most), 480x270, 64 chains x 12 frames after 800
# warm-up frames, fresh seeds (VR_SEED_BASE=3000000, clear of biasfinal's 2000000 + 64 x 10000), stats off (early
# rejection as it ships). Chain i has the same seed in both configs: bias_check.py --paired -- over the frame, the
# ground and the smoke (masks from the 960x540 noreuse run, resized). A finished capture is kept on rerun. Log: biassurface.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/biassurface.log
B=$O/biassurface/lanternglow_b2
SCRIPT_CP='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
cap() {  # config env...
    local cfg=$1
    shift
    local d="$R/$B/$cfg"
    mkdir -p "$d"
    if [ "$(ls "$d"/*.exr 2>/dev/null | wc -l)" -eq $((64 * 12)) ] && [ -f "$d/run.log" ] && ! grep -q '(Error)' "$d/run.log"; then
        echo "[$(date +%H:%M:%S)] $cfg: kept ($((64 * 12)) exr from an earlier run)" >> $LOG
        return
    fi
    ( for v in $(env | grep -o "^\(VR_\|NRD4_\|LANTERN_\)[A-Z0-9_]*"); do unset "$v"; done
      export MSYS_NO_PATHCONV=1 TEAPOT_FRAME=150 LANTERN_NIGHT=0.02 LANTERN_GROUND=-10.5,2000,0.05,0.05,0.05,0.1 \
             VR_SCENE=lanternglow VR_MAX_BOUNCES=2 VR_DISPLAY=480x270 VR_CHAINS=64 VR_PER_CHAIN=12 VR_SPACING=4 VR_WARM=800 \
             VR_IDS=0 VR_MTHRESH=200 VR_SEED_BASE=3000000 "$@"
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 14400 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    echo "[$(date +%H:%M:%S)] $cfg: $(ls "$d"/*.exr 2>/dev/null | wc -l) exr, $(grep -c '(Error)' "$d/run.log") errors" >> $LOG
}
echo "[$(date +%H:%M:%S)] biassurface start" >> $LOG
cap plain
cap mut5 VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce VR_MUT_STATS=0 VR_MUT_AFTER_SPATIAL=1
python - "$B" <<'PY'
import os, sys
import numpy as np, cv2
b = sys.argv[1]
med = np.load(r"outputs\decorr\previews\scene_wetground\lanternglow_b2\noreuse\c.medium.npy").astype(np.float32)
med = cv2.resize(med, (480, 270), interpolation=cv2.INTER_AREA) > 0.5
ground = (np.arange(270)[:, None] > 0.57 * 270) & ~med
np.save(os.path.join(b, "smoke.npy"), med)
np.save(os.path.join(b, "ground.npy"), ground)
print("masks: smoke %.1f%%, ground %.1f%% of the frame" % (100 * med.mean(), 100 * ground.mean()))
PY
for region in frame ground smoke; do
    m=(); [ $region = frame ] || m=(--mask "$B/$region.npy")
    python $O/bias_check.py "$B" plain mut5 --paired "${m[@]}" --save "$B/chains_$region.json" 2>&1 | sed "s/^/$region: /" | tee -a $LOG
done
echo "[$(date +%H:%M:%S)] biassurface done" >> $LOG
