#!/bin/bash
# Making the mutations' effect plain to the eye (spec V-B10). Reuse's blotches grow with how far and how long a
# sample is shared: spatial radius 30 (shipped 10) and M cap 200, plain ReSTIR vs the same with 5 and with 16 moves
# of all four kinds after spatial reuse (no decoupled history), through OptiX. First short VIDEOS -- 72 consecutive
# denoised frames at 1280x720 after the warm-up (one chain captured at spacing 1) (blotches crawl and boil from frame to frame, the plainest form of
# the artifact) -- written to outputs/decorr/video/<label>/<config>/ for make_video.py; then the full-resolution
# study runs for paper_figure.py. Scenes in order of how much mutations helped: cathedral, concert, sunset.
# Log: apparent.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/apparent.log
SCRIPT_CP=$(cygpath -w "$R/Source/RenderPasses/VolumetricReSTIR/Scripts/correlation_pose.py")
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
WIDE="VR_MTHRESH=200 VR_SR_RADIUS=30"
M5="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
M16="VR_MUTATIONS=16 VR_MUT_STRAT=light,depth,select,flight VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
scene_env() { case $1 in
    bunnycathedral_d0.3) echo "VR_SCENE=bunnycathedral VR_DENSITY_MULT=0.3" ;;
    plumeconcert_g0.6) echo "VR_SCENE=plumeconcert VR_PHASE_G=0.6" ;;
    wdassunset_g0.85) echo "VR_SCENE=wdassunset VR_PHASE_G=0.85" ;;
esac; }
while tasklist 2>/dev/null | grep -qi mogwai; do sleep 30; done
echo "[$(date +%H:%M:%S)] apparent start" >> $LOG
video() {  # label name [VAR=value...]
    local L=$1 name=$2; shift 2
    local d="$R/$O/video/$L/$name"  # absolute: frame capture writes nothing (or crashes) with a relative dir
    if ls "$d" 2>/dev/null | grep -q "Denoiser.output"; then echo "video $L/$name: exists" | tee -a $LOG; return 0; fi
    mkdir -p "$d"
    local t0=$SECONDS
    # shellcheck disable=SC2046,SC2086
    ( for v in $(env | grep -o "^VR_[A-Z0-9_]*"); do unset "$v"; done
      env $(scene_env $L) VR_DISPLAY=1280x720 VR_CHAINS=1 VR_PER_CHAIN=72 VR_WARM=800 VR_SPACING=1 \
          VR_DENOISER=optix $LOOK $WIDE "$@" VR_OUT_DIR="$(cygpath -m "$d")" VR_TAG=c \
          timeout 3600 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    echo "video $L/$name: $(ls "$d" | grep -c 'Denoiser.output.*exr') frames, $(grep -c '(Error)' "$d/run.log") errors, $((SECONDS - t0))s" | tee -a $LOG
}
for L in bunnycathedral_d0.3 plumeconcert_g0.6 wdassunset_g0.85; do
    video $L restir
    # shellcheck disable=SC2086
    video $L mut5 $M5
    # shellcheck disable=SC2086
    video $L mut16 $M16
done
echo "[$(date +%H:%M:%S)] apparent videos done" >> $LOG
export STUDY_SPACING=5
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
for L in bunnycathedral_d0.3 plumeconcert_g0.6 wdassunset_g0.85; do
    case $L in wdassunset*) export STUDY_TIMEOUT=10800 ;; *) export STUDY_TIMEOUT=5400 ;; esac
    # shellcheck disable=SC2086
    run $L den_optix_mut0cap200r30 VR_DENOISER=optix $LOOK $WIDE
    # shellcheck disable=SC2086
    run $L den_optix_mut16cap200r30 VR_DENOISER=optix $LOOK $WIDE $M16
    # shellcheck disable=SC2086
    run $L den_optix_mut5cap200r30 VR_DENOISER=optix $LOOK $WIDE $M5
done
echo "[$(date +%H:%M:%S)] apparent done" >> $LOG
