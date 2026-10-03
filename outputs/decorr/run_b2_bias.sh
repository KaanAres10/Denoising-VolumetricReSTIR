#!/bin/bash
# The two-bounce bias gate (spec; plan Task 5). bias_check.py needs every chain's frames and the study prunes its runs
# to 2, so the bias runs are dedicated unpruned 480x270 captures, as run_weighted_bias3.sh's were: 16 chains x 12
# frames at M cap 200 (warm 800 = 4 x cap) -- plain, + 5 moves of every kind, + 5 light-only moves (plan Review Focus
# 1-2: emission paths, the extra bounce every p_hat sees) -- each checked against plain with chain-level errors, then
# their EXRs deleted. The study's 2-bounce references and no-reuse runs (for the figures) come first. Log: b2.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/b2.log
B="$R/$O/b2bias"
SCRIPT_CP='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
ALL="light,depth,select,flight,direction,distance,rebounce"
LABELS="explosiondusk_b2 bunnycathedral_d0.3_b2 bunnyback_g0.8_b2 bunnysoftbox_b2 wdassunset_g0.85_b2"
scene_env() { bash -c 'eval "$(sed -n "/^scene_env()/,/^}/p" '"$O"'/run_study.sh)"; scene_env "$1"' _ "$1"; }
bias() {  # label config env...
    local label=$1 cfg=$2; shift 2
    local d="$B/$label/$cfg"
    if [ -f "$d/c.schedule.json" ] && [ "$(ls "$d"/*.exr 2>/dev/null | wc -l)" -ge 192 ]; then return 0; fi
    mkdir -p "$d"
    # shellcheck disable=SC2046
    ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
      export $(scene_env "$label") VR_DISPLAY=480x270 VR_CHAINS=16 VR_PER_CHAIN=12 VR_SPACING=4 VR_WARM=800 VR_IDS=0 \
             VR_MTHRESH=200 "$@"
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 7200 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    echo "[$(date +%H:%M:%S)] b2bias $label/$cfg: $(ls "$d"/*.exr 2>/dev/null | wc -l) exr $(grep -c '(Error)' "$d/run.log") errors" >> $LOG
}
echo "[$(date +%H:%M:%S)] b2 bias start" >> $LOG
export STUDY_SPACING=5 STUDY_REF_FRAMES=2048
for L in $LABELS; do
    case $L in wdassunset*|explosion*) export STUDY_TIMEOUT=10800 ;; *) export STUDY_TIMEOUT=7200 ;; esac
    bash $O/run_study.sh refs $L 2>&1 | tee -a $LOG
    bash $O/run_study.sh one $L noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1 2>&1 | tee -a $LOG
done
for L in $LABELS; do
    bias $L mcap200
    bias $L mcap200_mut5b2 VR_MUTATIONS=5 VR_MUT_STRAT=$ALL VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1
    bias $L mcap200_mut5light VR_MUTATIONS=5 VR_MUT_STRAT=light,select VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1
    python $O/bias_check.py "$B/$L" mcap200 mcap200_mut5b2 mcap200_mut5light 2>&1 | sed "s/^/bias $L: /" | tee -a $LOG
    for c in mcap200_mut5b2 mcap200_mut5light; do
        echo "moves $L/$c: $(grep -o 'bounce moves: .*' "$B/$L/$c/run.log" | tail -1)" | tee -a $LOG
    done
    rm -f "$B/$L"/*/c.*.exr  # the means are in the log; the captures are 400 MB a config
done
echo "[$(date +%H:%M:%S)] b2 bias done" >> $LOG
