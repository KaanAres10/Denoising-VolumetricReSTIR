#!/bin/bash
# The explosion's two-bounce rebounce, settled (final review of the two-bounce branch): the 16- and 64-chain gates used
# the same chain seeds in every config (correlation_pose.py: VR_SEED_BASE + i * stride) and bias_check's unpaired error
# bars, and never compared with a reference. Here: fresh seeds (VR_SEED_BASE=1000000, independent of both earlier runs),
# a converged 480x270 reference of the same pose, and plain / rebounce-only / all-moves at M cap 200, 64 chains each,
# read with paired error bars and against the reference. Chain means are kept in chains.json. Log: b2.log ("paired").
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/b2.log
B="$R/$O/b2bias_paired/explosiondusk_b2"
SCRIPT_CP='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
cap() {  # dir env...
    local d=$1; shift
    mkdir -p "$d"
    # shellcheck disable=SC2046
    ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
      export VR_SCENE=explosiondusk VR_MAX_BOUNCES=2 VR_DISPLAY=480x270 "$@"
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 10800 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    echo "[$(date +%H:%M:%S)] paired $(basename "$d"): $(ls "$d"/*.exr 2>/dev/null | wc -l) exr $(grep -c '(Error)' "$d/run.log") errors" >> $LOG
}
CH="VR_CHAINS=64 VR_PER_CHAIN=12 VR_SPACING=4 VR_WARM=800 VR_IDS=0 VR_MTHRESH=200 VR_SEED_BASE=1000000"
M="VR_MUTATIONS=5 VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
echo "[$(date +%H:%M:%S)] paired start" >> $LOG
cap "$B/ref" VR_MODE=reference VR_FRAMES=8192 VR_SPP=16
# shellcheck disable=SC2086
cap "$B/mcap200" $CH
# shellcheck disable=SC2086
cap "$B/mut5_rebounce" $CH $M VR_MUT_STRAT=rebounce
# shellcheck disable=SC2086
cap "$B/mut5_all" $CH $M VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce
REF=$(ls "$B"/ref/c.Accum.output.*.exr | sort -t. -k4 -n | tail -1)
python $O/bias_check.py "$B" mcap200 mut5_rebounce mut5_all --paired --ref "$REF" --save "$B/chains.json" 2>&1 \
    | sed "s/^/paired explosiondusk_b2: /" | tee -a $LOG
python $O/bias_check.py "$B" mcap200 mut5_rebounce mut5_all 2>&1 | sed "s/^/paired (unpaired s.e.) explosiondusk_b2: /" | tee -a $LOG
rm -f /c/research/Denoising-VolumetricReSTIR/outputs/decorr/b2bias_paired/explosiondusk_b2/mcap200/c.*.exr \
      /c/research/Denoising-VolumetricReSTIR/outputs/decorr/b2bias_paired/explosiondusk_b2/mut5_rebounce/c.*.exr \
      /c/research/Denoising-VolumetricReSTIR/outputs/decorr/b2bias_paired/explosiondusk_b2/mut5_all/c.*.exr
echo "[$(date +%H:%M:%S)] paired done" >> $LOG
