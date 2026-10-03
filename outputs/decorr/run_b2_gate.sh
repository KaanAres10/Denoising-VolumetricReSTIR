#!/bin/bash
# Step 0 of the two-bounce spec: plain 2-bounce ReSTIR in the port vs the legacy build and a 2-bounce reference.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/b2.log
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
echo "[$(date +%H:%M:%S)] b2 gate start" >> $LOG
# 1. Legacy, 2 bounces, 1024 accumulated frames at 960x540.
L="$R/$O/legacy_b2"; mkdir -p "$L"
( cd legacy/Bin/x64/Release && FALCOR_MEDIA_FOLDERS="$(cygpath -w "$R/VolumetricReSTIRData");$(cygpath -w "$R/legacy/Media")" \
  LEG_OUT="$(cygpath -w "$L")" LEG_FRAMES=1024 LEG_BOUNCES=2 timeout 1800 ./Mogwai.exe --script "$(cygpath -w "$R/$O/legacy_explosion.py")" > "$L/run.log" 2>&1 )
echo "[$(date +%H:%M:%S)] legacy b2: $(ls "$L"/*.exr 2>/dev/null | wc -l) exr" >> $LOG
# 2. The port's 2-bounce reference at the same size (study reference: 1080p, 2048 frames).
P="$R/$O/explosiondusk_b2/ref960"; mkdir -p "$P"
( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
  VR_SCENE=explosiondusk VR_MAX_BOUNCES=2 VR_MODE=reference VR_FRAMES=1024 VR_SPP=4 VR_DISPLAY=960x540 \
  VR_OUT_DIR="$(cygpath -am "$P")" VR_TAG=p timeout 3600 ./build/windows-vs2022/bin/Release/Mogwai.exe \
  --script 'C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py' > "$P/run.log" 2>&1 )
echo "[$(date +%H:%M:%S)] port b2 ref960: $(ls "$P"/*.exr 2>/dev/null | wc -l) exr" >> $LOG
# 3. The study's 2-bounce reference, no reuse and shipped (scored against the reference).
export STUDY_SPACING=5 STUDY_REF_FRAMES=2048 STUDY_TIMEOUT=7200
bash $O/run_study.sh refs explosiondusk_b2 2>&1 | tee -a $LOG
bash $O/run_study.sh one explosiondusk_b2 noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1 2>&1 | tee -a $LOG
bash $O/run_study.sh one explosiondusk_b2 shipped 2>&1 | tee -a $LOG
echo "[$(date +%H:%M:%S)] b2 gate done" >> $LOG
