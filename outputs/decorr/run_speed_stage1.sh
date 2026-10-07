#!/bin/bash
# Stage 1 of the mutation speed-up, end to end, started detached while the equal-time runs hold the GPU: wait for
# them to finish, build, check the build installed the working tree's MutateSamples, smoke-render it at one and two
# bounces (a shader error would otherwise hang every A/B run on Falcor's dialog until its timeout), then A/B it
# against HEAD's (run_speed_ab.sh stage1). Both shaders are copied first, so later edits to the tree change nothing.
# Log: speed_ab.log.
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
mkdir -p $S
git show HEAD:$SRC > $S/MutateSamples.head.cs.slang
cp $SRC $S/MutateSamples.stage1.cs.slang
echo "[$(date +%H:%M:%S)] stage1: waiting for the equal-time runs" >> $LOG
until grep -q "equal time done" $O/eqtime.log; do
    ps -ef | grep -v grep | grep -q "run_equal_time.sh" || { echo "[$(date +%H:%M:%S)] stage1: equal-time runs gone without 'done'; abort" >> $LOG; exit 1; }
    sleep 60
done
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 30; done
./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target VolumetricReSTIR > $S/build_stage1.log 2>&1 \
    || { echo "[$(date +%H:%M:%S)] stage1: BUILD FAILED (see $S/build_stage1.log)" >> $LOG; exit 1; }
cmp -s $BIN $S/MutateSamples.stage1.cs.slang || { echo "[$(date +%H:%M:%S)] stage1: the build did not install the stage-1 shader; abort" >> $LOG; exit 1; }
# The plugin build drops runtime DLLs Mogwai needs (libprotoc, z); run_study.sh restores them the same way.
ls build/windows-vs2022/bin/Release/libprotoc.dll build/windows-vs2022/bin/Release/z.dll > /dev/null 2>&1 ||
    ./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target restore_runtime_dlls > $S/restore_dlls.log 2>&1
for b in 1 2; do
    d="$R/$S/smoke_b$b"
    mkdir -p "$d"
    ( for x in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$x"; done
      export VR_SCENE=bunnysoftbox VR_MAX_BOUNCES=$b VR_DISPLAY=480x270 VR_CHAINS=1 VR_PER_CHAIN=1 VR_SPACING=1 VR_WARM=16 \
             VR_IDS=0 VR_MTHRESH=200 VR_MUTATIONS=5 VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1 \
             VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 900 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    if [ "$(ls "$d"/*.exr 2>/dev/null | wc -l)" = 0 ] || grep -q "(Error)" "$d/run.log"; then
        echo "[$(date +%H:%M:%S)] stage1: SMOKE FAILED at $b bounce(s) (see $d/run.log)" >> $LOG
        exit 1
    fi
    echo "[$(date +%H:%M:%S)] stage1: smoke ok at $b bounce(s): $(grep -h "mutations, last" "$d/run.log" | tail -1 | cut -c1-160)" >> $LOG
done
bash $O/run_speed_ab.sh stage1 $S/MutateSamples.head.cs.slang $S/MutateSamples.stage1.cs.slang
