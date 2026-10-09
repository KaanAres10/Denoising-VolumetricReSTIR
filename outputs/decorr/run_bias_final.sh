#!/bin/bash
# Is the mutation pass, as it now ships, unbiased? (user, 2026-10-08: "prove unbiasedness of our mutation pass")
# The pass's defaults -- coherent moves (Stage 2), early rejection (A), 5 mutations of every kind after spatial
# reuse -- against plain ReSTIR, on all ten setups (five first-round scenes at 1 and 2 bounces), M cap 200, 480x270,
# 64 chains x 12 frames after 800 warm-up frames, fresh seeds (VR_SEED_BASE=2000000, clear of every earlier test's
# 100000-1000000+64*10000), stats off (so the early rejection runs as it ships). Chain i has the same seed in both
# configs: bias_check.py --paired. Each setup's chain means are kept (chains.json) and its EXRs deleted (the disk).
# Then bias_summary.py: every setup's luminance bias in standard errors, and their chi-square. Log: biasfinal.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/biasfinal.log
B=$O/biasfinal
SCRIPT_CP='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
scene_env() { bash -c 'eval "$(sed -n "/^scene_env()/,/^}/p" '"$O"'/run_study.sh)"; scene_env "$1"' _ "$1"; }
cap() {  # label config env...
    local label=$1 cfg=$2
    shift 2
    local d="$R/$B/$label/$cfg"
    mkdir -p "$d"
    # A capture that finished before the queue was cut off (all 64 x 12 frames, no errors) is kept, not re-rendered.
    if [ "$(ls "$d"/*.exr 2>/dev/null | wc -l)" -eq $((64 * 12)) ] && [ -f "$d/run.log" ] && ! grep -q '(Error)' "$d/run.log"; then
        echo "[$(date +%H:%M:%S)] $label/$cfg: kept ($((64 * 12)) exr from an earlier run)" >> $LOG
        return
    fi
    # shellcheck disable=SC2046
    ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
      export $(scene_env "$label") VR_DISPLAY=480x270 VR_CHAINS=64 VR_PER_CHAIN=12 VR_SPACING=4 VR_WARM=800 VR_IDS=0 \
             VR_MTHRESH=200 VR_SEED_BASE=2000000 "$@"
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 10800 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    echo "[$(date +%H:%M:%S)] $label/$cfg: $(ls "$d"/*.exr 2>/dev/null | wc -l) exr, $(grep -c '(Error)' "$d/run.log") errors" >> $LOG
}
echo "[$(date +%H:%M:%S)] biasfinal start" >> $LOG
for L in explosiondusk bunnycathedral_d0.3 bunnyback_g0.8 bunnysoftbox wdassunset_g0.85 \
         explosiondusk_b2 bunnycathedral_d0.3_b2 bunnyback_g0.8_b2 bunnysoftbox_b2 wdassunset_g0.85_b2; do
    [ -f "$B/$L/chains.json" ] && continue
    S=light,depth,select,flight
    case $L in *_b2) S=$S,direction,distance,rebounce ;; esac
    cap "$L" plain
    cap "$L" mut5 VR_MUTATIONS=5 VR_MUT_STRAT=$S VR_MUT_STATS=0 VR_MUT_AFTER_SPATIAL=1
    python $O/bias_check.py "$B/$L" plain mut5 --paired --save "$B/$L/chains.json" 2>&1 | sed "s/^/$L: /" | tee -a $LOG
    if [ -f "$B/$L/chains.json" ]; then
        rm -f "/c/research/Denoising-VolumetricReSTIR/outputs/decorr/biasfinal/${L:?}/plain/"c.*.exr \
              "/c/research/Denoising-VolumetricReSTIR/outputs/decorr/biasfinal/${L:?}/mut5/"c.*.exr
    fi
done
python $O/bias_summary.py $B 2>&1 | tee -a $LOG
echo "[$(date +%H:%M:%S)] biasfinal done" >> $LOG
