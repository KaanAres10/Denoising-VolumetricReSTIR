#!/bin/bash
# Where temporal reuse's brightening on the plume comes from: short plume renders (960x540, 2 chains x 10
# captures after the usual warm-up) with one temporal-reuse path switched off at a time, each scored as
# its whole-image mean over the captures relative to no reuse (unbiased: it matches the path-traced
# reference to 0.1%). Runs as VRDiag.exe, a copy of Mogwai, so run_study.sh's "Mogwai is running" guard
# does not mistake it for a study run.
#
#   bias_diag.sh [scene]      (default plume)      -> one line per config
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
BIN=./build/windows-vs2022/bin/Release
[ -f $BIN/VRDiag.exe ] || cp $BIN/Mogwai.exe $BIN/VRDiag.exe
SCRIPT='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
OUT=${DIAG_OUT:-.superpowers/sdd/2026-09-27-restir-mcmc-decorrelation/bias_diag}
scene=${1:-plume}

run() {  # name, then env assignments
    local d=$OUT/$scene/$1
    shift
    if [ ! -f "$d/c.schedule.json" ]; then
        rm -rf "$d"
        mkdir -p "$d"
        (
            for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
            export VR_SCENE=$scene VR_DISPLAY=${DIAG_DISPLAY:-960x540} VR_CHAINS=2 VR_PER_CHAIN=10 VR_SPACING=5 VR_IDS=0 "$@"
            VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 1800 $BIN/VRDiag.exe --script "$SCRIPT" > "$d/run.log" 2>&1
        )
    fi
    python - "$d" <<'PY'
import glob, os, sys
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2, numpy as np
fs = sorted(glob.glob(os.path.join(sys.argv[1], "c.VolumetricReSTIR.accumulated_color.*.exr")))
m = np.mean([cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float64) @ [0.0722, 0.7152, 0.2126] for f in fs], axis=0)
print("%.6f %d" % (m.mean(), len(fs)))
PY
}

base=$(run noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1 | cut -d' ' -f1)
echo "$scene noreuse mean $base"
report() {  # name, env...
    local name=$1
    shift
    local r
    r=$(run "$name" "$@")
    python -c "import sys; m, n = sys.argv[1].split(); print('%-28s mean %s  (%d captures)  vs noreuse %+.2f%%' % (sys.argv[2], m, int(n), 100 * (float(m) / float(sys.argv[3]) - 1)))" "$r" "$name" "$base"
}
report temporal VR_NO_SPATIAL=1
[ -n "${DIAG_ONLY_IDS:-}" ] && { report temporal_ids VR_NO_SPATIAL=1 VR_IDS=1; exit 0; }
report temporal_noMIS VR_NO_SPATIAL=1 'VR_PARAMS={"mTemporalMISMethod": 0}'
report temporal_noReproj VR_NO_SPATIAL=1 'VR_PARAMS={"mTemporalReprojectionMode": 1}'
report temporal_reprojNoBackground VR_NO_SPATIAL=1 'VR_PARAMS={"mTemporalReprojectionMode": 2}'
report temporal_noPrevVolume VR_NO_SPATIAL=1 'VR_PARAMS={"mUsePrevVolumeForReproj": false}'
report temporal_mcap1 VR_NO_SPATIAL=1 VR_MTHRESH=1
