#!/bin/bash
# Speed-up B's probe (user, 2026-10-07: "do A, then B, then C"): does a mutation program built for ONE move kind run
# that kind faster than the program that carries all seven (fewer registers, more warps in flight)? Per scene setup and
# kind, 5 mutations of that kind alone (VR_MUT_STRAT=<kind>), A = the shader as it is (runtime mask), B = the same with
# VR_MUT_STATIC_MASK set to that kind (the compiler drops every other move's code). A B B A, the runtime shader copy
# swapped (run_speed_ab.sh's method); frames must match bit for bit. Needs the GPU to itself. Table: speed_ab_check.py
# on outputs/decorr/speed_ab/probeB/<label>_<kind>. Log: speed_ab.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/speed_ab.log
S=$O/speed_ab
SCRIPT_CP='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
SRC=Source/RenderPasses/VolumetricReSTIR/MutateSamples.cs.slang
BIN_SHADER=build/windows-vs2022/bin/Release/shaders/RenderPasses/VolumetricReSTIR/MutateSamples.cs.slang
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
mkdir -p $S/probeB
cp $SRC $S/probeB/MutateSamples.dynamic.cs.slang
trap 'cp "$S/probeB/MutateSamples.dynamic.cs.slang" "$BIN_SHADER"' EXIT
bit() { case $1 in light) echo 1u ;; depth) echo 2u ;; select) echo 4u ;; flight) echo 8u ;; direction) echo 16u ;; distance) echo 32u ;; rebounce) echo 64u ;; esac; }
scene_env() { bash -c 'eval "$(sed -n "/^scene_env()/,/^}/p" '"$O"'/run_study.sh)"; scene_env "$1"' _ "$1"; }
run() {  # label kind variant shader
    local label=$1 kind=$2 v=$3 shader=$4
    local d="$R/$S/probeB/${label}_$kind/$v"
    [ -f "$d/c.passes.json" ] && return 0
    mkdir -p "$d"
    cp "$shader" "$BIN_SHADER"
    # shellcheck disable=SC2046
    ( for x in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$x"; done
      export $(scene_env "$label") VR_DISPLAY=1920x1080 VR_CHAINS=1 VR_PER_CHAIN=4 VR_SPACING=8 VR_WARM=64 VR_IDS=0 \
             VR_MTHRESH=200 VR_PASS_TIMES=1 VR_MUTATIONS=5 VR_MUT_STATS=0 VR_MUT_AFTER_SPATIAL=1 VR_MUT_STRAT=$kind
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 1200 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    echo "[$(date +%H:%M:%S)] probeB ${label}_$kind/$v: $(ls "$d"/*.exr 2>/dev/null | wc -l) exr, $(grep -c '(Error)' "$d/run.log") errors" >> $LOG
}
echo "[$(date +%H:%M:%S)] probeB start" >> $LOG
for spec in bunnysoftbox:light bunnysoftbox:depth bunnysoftbox:select bunnysoftbox:flight \
            bunnysoftbox_b2:select bunnysoftbox_b2:flight bunnysoftbox_b2:direction bunnysoftbox_b2:rebounce; do
    L=${spec%%:*} K=${spec#*:}
    st=$S/probeB/MutateSamples.static_$K.cs.slang
    { echo "#define VR_MUT_STATIC_MASK $(bit $K)"; cat $S/probeB/MutateSamples.dynamic.cs.slang; } > "$st"
    run "$L" "$K" A1 $S/probeB/MutateSamples.dynamic.cs.slang
    run "$L" "$K" B1 "$st"
    run "$L" "$K" B2 "$st"
    run "$L" "$K" A2 $S/probeB/MutateSamples.dynamic.cs.slang
done
echo "[$(date +%H:%M:%S)] probeB done" >> $LOG
python $O/speed_ab_check.py $S/probeB 2>&1 | sed "s/^/probeB: /" | tee -a $LOG
