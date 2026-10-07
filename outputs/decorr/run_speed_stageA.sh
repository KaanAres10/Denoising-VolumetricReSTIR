#!/bin/bash
# Speed-up A, early rejection (user, 2026-10-07: "do A, then B, then C"): a proposal's shadow march stops once p_hat(z)
# provably cannot be accepted. Build, smoke-render at one and two bounces, then A/B the switch in this one binary --
# A off (VR_MUT_EARLY_REJECT=0), B on (the default) -- run_speed_ab.sh stageA. Every decision is the full value's, so:
#   - A and B render the same frames bit for bit (speed_ab_check.py), and
#   - A renders Stage 2's frames (--against stage2: the shared p_hat code with no threshold changed nothing), and
#   - plain ReSTIR (no mutations) renders run_cost.sh's mut0 frames: the other passes compile as before.
# Needs the GPU to itself. Log: speed_ab.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/speed_ab.log
SCRIPT_CP='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
SRC=Source/RenderPasses/VolumetricReSTIR/MutateSamples.cs.slang
S=$O/speed_ab
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
cp $SRC $S/MutateSamples.stageA.cs.slang
./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target VolumetricReSTIR > $S/build_stageA.log 2>&1 \
    || { echo "[$(date +%H:%M:%S)] stageA: BUILD FAILED (see $S/build_stageA.log)" >> $LOG; exit 1; }
# The plugin build drops runtime DLLs Mogwai needs (libprotoc, z); run_study.sh restores them the same way.
ls build/windows-vs2022/bin/Release/libprotoc.dll build/windows-vs2022/bin/Release/z.dll > /dev/null 2>&1 ||
    ./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target restore_runtime_dlls > $S/restore_dlls.log 2>&1
scene_env() { bash -c 'eval "$(sed -n "/^scene_env()/,/^}/p" '"$O"'/run_study.sh)"; scene_env "$1"' _ "$1"; }
render() {  # dir label env...
    local d=$1 label=$2
    shift 2
    mkdir -p "$d"
    # shellcheck disable=SC2046
    ( for x in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$x"; done
      export $(scene_env "$label") "$@"
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 1200 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
}
for b in 1 2; do
    d="$R/$S/smokeA_b$b"
    render "$d" bunnysoftbox VR_MAX_BOUNCES=$b VR_DISPLAY=480x270 VR_CHAINS=1 VR_PER_CHAIN=1 VR_SPACING=1 VR_WARM=16 VR_IDS=0 \
        VR_MTHRESH=200 VR_MUTATIONS=5 VR_MUT_STATS=0 VR_MUT_AFTER_SPATIAL=1 VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce
    if [ "$(ls "$d"/*.exr 2>/dev/null | wc -l)" = 0 ] || grep -q "(Error)" "$d/run.log"; then
        echo "[$(date +%H:%M:%S)] stageA: SMOKE FAILED at $b bounce(s) (see $d/run.log)" >> $LOG
        exit 1
    fi
    echo "[$(date +%H:%M:%S)] stageA: smoke ok at $b bounce(s)" >> $LOG
done
# Plain ReSTIR against run_cost.sh's mut0 frames (the binary before A), on a 1- and 2-bounce scene and a surface scene.
for L in explosiondusk explosiondusk_b2 bunnycathedral_d0.3_b2; do
    render "$R/$S/plainA/$L" "$L" VR_DISPLAY=1920x1080 VR_CHAINS=1 VR_PER_CHAIN=4 VR_SPACING=8 VR_WARM=192 VR_IDS=0 VR_MTHRESH=200 \
        VR_PASS_TIMES=1
    python -c "
import sys; sys.path.insert(0, '$O')
import speed_ab_check as ab
c = ab.compare('$S/plainA/$L', '$O/cost/$L/mut0')
print('stageA: plain $L vs before A: %d/%d frames identical, %d pixels differ' % (c['identical'], c['frames'], c['pixels_differ']))" >> $LOG
done
SPEED_AB_AENV="VR_MUT_EARLY_REJECT=0" bash $O/run_speed_ab.sh stageA $S/MutateSamples.stageA.cs.slang $S/MutateSamples.stageA.cs.slang
python $O/speed_ab_check.py $S/stageA --against $S/stage2 2>&1 | sed "s/^/stageA off vs stage2: /" | tee -a $LOG
