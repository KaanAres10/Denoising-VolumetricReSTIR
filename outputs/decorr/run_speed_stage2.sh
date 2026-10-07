#!/bin/bash
# Stage 2 of the mutation speed-up: build the tree (Stage 2: mMutationCoherentMoves, the no-op re-selection skipped),
# smoke-render it with the switch on at one and two bounces, then A/B the switch in this one binary -- A off, B on
# (VR_MUT_COHERENT=1) -- run_speed_ab.sh stage2. A must render Stage 1's frames bit for bit (the skip is exact;
# speed_ab_check.py --against compares A1 with stage1's B1); B changes the images and is judged on quality separately.
# Needs the GPU to itself. Log: speed_ab.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/speed_ab.log
SCRIPT_CP='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
SRC=Source/RenderPasses/VolumetricReSTIR/MutateSamples.cs.slang
BIN=build/windows-vs2022/bin/Release/shaders/RenderPasses/VolumetricReSTIR/MutateSamples.cs.slang
S=$O/speed_ab
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
cp $SRC $S/MutateSamples.stage2.cs.slang
./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target VolumetricReSTIR > $S/build_stage2.log 2>&1 \
    || { echo "[$(date +%H:%M:%S)] stage2: BUILD FAILED (see $S/build_stage2.log)" >> $LOG; exit 1; }
cmp -s $BIN $S/MutateSamples.stage2.cs.slang || { echo "[$(date +%H:%M:%S)] stage2: the build did not install the stage-2 shader; abort" >> $LOG; exit 1; }
# The plugin build drops runtime DLLs Mogwai needs (libprotoc, z); run_study.sh restores them the same way.
ls build/windows-vs2022/bin/Release/libprotoc.dll build/windows-vs2022/bin/Release/z.dll > /dev/null 2>&1 ||
    ./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target restore_runtime_dlls > $S/restore_dlls.log 2>&1
for b in 1 2; do
    d="$R/$S/smoke2_b$b"
    mkdir -p "$d"
    ( for x in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$x"; done
      export VR_SCENE=bunnysoftbox VR_MAX_BOUNCES=$b VR_DISPLAY=480x270 VR_CHAINS=1 VR_PER_CHAIN=1 VR_SPACING=1 VR_WARM=16 \
             VR_IDS=0 VR_MTHRESH=200 VR_MUTATIONS=5 VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1 VR_MUT_COHERENT=1 \
             VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 900 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    if [ "$(ls "$d"/*.exr 2>/dev/null | wc -l)" = 0 ] || grep -q "(Error)" "$d/run.log"; then
        echo "[$(date +%H:%M:%S)] stage2: SMOKE FAILED at $b bounce(s) (see $d/run.log)" >> $LOG
        exit 1
    fi
    echo "[$(date +%H:%M:%S)] stage2: smoke ok at $b bounce(s)" >> $LOG
done
bash $O/run_speed_ab.sh stage2 $S/MutateSamples.stage2.cs.slang $S/MutateSamples.stage2.cs.slang VR_MUT_COHERENT=1
python $O/speed_ab_check.py $S/stage2 --against $S/stage1 2>&1 | sed "s/^/stage2 vs stage1: /" | tee -a $LOG
