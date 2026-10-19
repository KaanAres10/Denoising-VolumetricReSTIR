#!/bin/bash
# The bounce moves at a surface first vertex, measured (user, 2026-10-19), after the bias gate (run_bias_surface.sh):
# the wet ground at the shipped M cap 4 (scene_check.sh's settings: 960x540, 2 chains x 2, its ref, noreuse and plain
# runs kept), 5 mutations of ALL SEVEN kinds -- the earlier construct checks passed only the four first-vertex
# moves -- once with the shader as committed (no surface moves: *_mut5all_old) and once with the new one
# (*_mut5all), the shader swapped in the binary's shaders dir between them (the C++ only adds counter names); then the
# baseline glow scene (previews/glownospark) with all seven kinds, the new shader. Log: surfaceeval.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$R/$O/surfaceeval.log
SRC=Source/RenderPasses/VolumetricReSTIR/MutateSamples.cs.slang
BIN=build/windows-vs2022/bin/Release/shaders/RenderPasses/VolumetricReSTIR/MutateSamples.cs.slang
OLD=$O/surface_moves/MutateSamples.committed.cs.slang
until grep -q "biassurface done" $O/biassurface.log 2>/dev/null; do sleep 20; done
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 5; done
mkdir -p $O/surface_moves
git show HEAD:$SRC > $OLD
export MSYS_NO_PATHCONV=1 STUDY_REF_FRAMES=1024 STUDY_SPACING=5 STUDY_CHAINS=2 STUDY_PER_CHAIN=2 STUDY_TIMEOUT=7200 \
       STUDY_DISPLAY=960x540 TEAPOT_FRAME=150
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
MUT="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
L=lanternglow_b2
three() {  # suffix: OptiX, DLSS RR and raw, 5 mutations of all seven kinds
    # shellcheck disable=SC2086
    bash $O/run_study.sh one $L den_optix_mut5all$1 VR_DENOISER=optix $LOOK $MUT
    # shellcheck disable=SC2086
    bash $O/run_study.sh one $L den_rr_mut5all$1 VR_DENOISER=rr $LOOK $MUT
    # shellcheck disable=SC2086
    bash $O/run_study.sh one $L mut5all$1 $MUT
}
{
echo "[surfaceeval] start $(date +%H:%M)"
( export STUDY_OUT=$O/previews/scene_wetground LANTERN_NIGHT=0.02 LANTERN_GROUND=-10.5,2000,0.05,0.05,0.05,0.1
  cp $OLD $BIN && cmp -s $OLD $BIN && echo "[surfaceeval] committed shader in place" && three _old
  cp $SRC $BIN && cmp -s $SRC $BIN && echo "[surfaceeval] new shader in place" && three "" )
cmp -s $SRC $BIN || { echo "[surfaceeval] FAILED: the new shader is not back in place"; exit 1; }
( export STUDY_OUT=$O/previews/glownospark; three "" )
echo "[surfaceeval] done $(date +%H:%M)"
} >> "$LOG" 2>&1
