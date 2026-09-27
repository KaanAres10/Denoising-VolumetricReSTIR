#!/bin/bash
# Plan Task 10, the unbiasedness gate: mutations must not move the converged image.
#   A  plume under ONE point light (bias_test_plume.py, 960x540, 4096 frames): path-traced reference vs
#      ReSTIR with 0 and 5 mutations. A delta light, so only the scatter-depth moves apply.
#   B  bistro at the verify pose (forkref/run.sh, 4096 frames): mutations 0 / 1 / 5, each scored against
#      the path-traced v9sa_ref by forkref/score.py (region bias with error bars).
#   C  plume (env map: light moves on directions) and explosion (self-emission: depth moves) at 1080p,
#      correlation_pose.py chains: no reuse / 0 / 5 mutations, image and centre-box means.
# Output: outputs/decorr/gate/ (logs, captures) and gate.log.   gate.sh [A] [B] [C]  (default all)
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
G=$R/outputs/decorr/gate
LOG=$R/outputs/decorr/gate.log
BIN=./build/windows-vs2022/bin/Release
SCRIPTS='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts'
mkdir -p "$G"
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
clean_env() { for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done; }
parts=${*:-A B C}

if [[ $parts == *A* ]]; then
    for run in reference:0 restir:0 restir:5; do
        mode=${run%%:*} n=${run#*:}
        tag=${mode}_m$n
        [ -f "$G/A/plume_$tag.AccumulatePass.output.4096.exr" ] && continue
        mkdir -p "$G/A"
        ( clean_env; export VR_MODE=$mode VR_FRAMES=4096 VR_MUTATIONS=$n VR_MUT_STATS=1 VR_TAG=_m$n VR_EXIT=1
          VR_OUT_DIR="$(cygpath -w "$G/A")" timeout 3600 $BIN/Mogwai.exe --script "$SCRIPTS\\bias_test_plume.py" > "$G/A/$tag.log" 2>&1 )
        say "A $tag: $(ls "$G/A/plume_$tag."*.exr 2>/dev/null | wc -l) capture(s); $(grep 'VolumetricReSTIR mutations' "$G/A/$tag.log" | tail -1 | cut -c8-150)"
    done
    python - "$G/A" <<'PY' | tee -a "$LOG"
import os, sys
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2, numpy as np
d = sys.argv[1]
Y = np.array([0.0722, 0.7152, 0.2126])
img = lambda t: cv2.imread(os.path.join(d, "plume_%s.AccumulatePass.output.4096.exr" % t), cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float64) @ Y
ref = img("reference_m0")
H, W = ref.shape
box = np.s_[H // 5:4 * H // 5, W // 3:2 * W // 3]
for t in ("restir_m0", "restir_m5"):
    x = img(t)
    print("A %-10s whole %+.2f%%  plume box %+.2f%%  MSE %.3e  (vs the path-traced reference)" % (
        t, 100 * (x.mean() / ref.mean() - 1), 100 * (x[box].mean() / ref[box].mean() - 1), np.mean((x - ref) ** 2)))
PY
fi

if [[ $parts == *B* ]]; then
    for n in 0 1 5; do
        tag=gate_m$n
        [ "$(ls "$R/outputs/pending_9p/forkref/cap/$tag"/*.exr 2>/dev/null | wc -l)" -gt 0 ] && continue
        bash outputs/pending_9p/forkref/run.sh v9 restir 4096 1 $tag VR_MUTATIONS=$n VR_MUT_STATS=1 | tee -a "$LOG"
        say "B $tag: $(grep 'VolumetricReSTIR mutations' "$R/outputs/pending_9p/forkref/cap/$tag.log" | tail -1 | cut -c8-150)"
    done
    (cd outputs/pending_9p/forkref && python score.py gate_m0@v9sa gate_m1@v9sa gate_m5@v9sa) 2>&1 | tee "$G/B_score.txt" | tee -a "$LOG" | tail -40
fi

if [[ $parts == *C* ]]; then
    for scene in plume explosion; do
        for cfg in noreuse:VR_NO_TEMPORAL=1:VR_NO_SPATIAL=1 m0:VR_MUTATIONS=0 m5:VR_MUTATIONS=5:VR_MUT_STATS=1; do
            name=${cfg%%:*}
            d=$G/C/$scene/$name
            [ -f "$d/c.schedule.json" ] && continue
            mkdir -p "$d"
            IFS=: read -r -a kv <<< "${cfg#*:}"
            ( clean_env; export VR_SCENE=$scene VR_DISPLAY=1920x1080 VR_CHAINS=2 VR_PER_CHAIN=20 VR_SPACING=5 VR_IDS=0 "${kv[@]}"
              VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 3600 $BIN/Mogwai.exe --script "$SCRIPTS\\correlation_pose.py" > "$d/run.log" 2>&1 )
            say "C $scene/$name: $(ls "$d"/*.exr 2>/dev/null | wc -l) captures; $(grep 'VolumetricReSTIR mutations' "$d/run.log" | tail -1 | cut -c8-150)"
        done
        python - "$G/C/$scene" "$scene" <<'PY' | tee -a "$LOG"
import glob, os, sys
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2, numpy as np
Y = np.array([0.0722, 0.7152, 0.2126])
def mean(d):
    acc, fs = None, sorted(glob.glob(os.path.join(d, "c.VolumetricReSTIR.accumulated_color.*.exr")))
    for p in fs:
        v = cv2.imread(p, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float64) @ Y
        acc = v if acc is None else acc + v
    return acc / len(fs), len(fs)
base, _ = mean(os.path.join(sys.argv[1], "noreuse"))
H, W = base.shape
box = np.s_[H // 5:4 * H // 5, W // 3:2 * W // 3]
for c in ("m0", "m5"):
    x, n = mean(os.path.join(sys.argv[1], c))
    print("C %-9s %s: whole %+.2f%%  centre box %+.2f%%  vs no reuse (%d captures)" % (
        sys.argv[2], c, 100 * (x.mean() / base.mean() - 1), 100 * (x[box].mean() / base[box].mean() - 1), n))
PY
    done
fi
say "gate done: $parts"
