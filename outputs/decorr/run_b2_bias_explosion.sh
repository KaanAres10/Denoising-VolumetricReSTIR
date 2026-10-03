#!/bin/bash
# The explosion's two-bounce bias, sharper (follow-up to run_b2_bias.sh, where 5 moves of every kind read +3.0% / +1.8%
# / +0.1% +- 1.4 / 1.0 / 0.3% in R/G/B against plain reuse at M cap 200 -- about 2 s.e. in the two channels the fire
# dominates). 64 chains x 12 frames at 480x270 (4x the chains: half the error bars), and each move kind alone, so a real
# bias is pinned to a move: the existing moves (bounce-aware), direction, distance, rebounce, and all of them.
# Log: b2.log ("bias64 ..." lines).
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/b2.log
B="$R/$O/b2bias64"
L=explosiondusk_b2
SCRIPT_CP='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
bias() {  # config env...
    local cfg=$1; shift
    local d="$B/$L/$cfg"
    if [ -f "$d/c.schedule.json" ] && [ "$(ls "$d"/*.exr 2>/dev/null | wc -l)" -ge 768 ]; then return 0; fi
    mkdir -p "$d"
    # shellcheck disable=SC2046
    ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
      export VR_SCENE=explosiondusk VR_MAX_BOUNCES=2 VR_DISPLAY=480x270 VR_CHAINS=64 VR_PER_CHAIN=12 VR_SPACING=4 \
             VR_WARM=800 VR_IDS=0 VR_MTHRESH=200 "$@"
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 10800 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    echo "[$(date +%H:%M:%S)] bias64 $L/$cfg: $(ls "$d"/*.exr 2>/dev/null | wc -l) exr $(grep -c '(Error)' "$d/run.log") errors" >> $LOG
}
M="VR_MUTATIONS=5 VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
echo "[$(date +%H:%M:%S)] bias64 start" >> $LOG
bias mcap200
# shellcheck disable=SC2086
bias mut5_existing $M VR_MUT_STRAT=light,depth,select,flight
# shellcheck disable=SC2086
bias mut5_direction $M VR_MUT_STRAT=direction
# shellcheck disable=SC2086
bias mut5_distance $M VR_MUT_STRAT=distance
# shellcheck disable=SC2086
bias mut5_rebounce $M VR_MUT_STRAT=rebounce
# shellcheck disable=SC2086
bias mut5_all $M VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce
python $O/bias_check.py "$B/$L" mcap200 mut5_existing mut5_direction mut5_distance mut5_rebounce mut5_all 2>&1 | sed "s/^/bias64 $L: /" | tee -a $LOG
rm -f "$B/$L"/*/c.*.exr
echo "[$(date +%H:%M:%S)] bias64 done" >> $LOG
