#!/bin/bash
# Mutations AFTER spatial reuse (mMutateAfterSpatial, spec V-B9): the residual colour clumping with a decoupled
# history is made within the frame by spatial reuse, which mutations placed after temporal reuse cannot reach;
# mutating the shaded reservoir can. First on the colour stress scenes, then the plume / emerald / bistro
# matrix (with the new placement next to the old). Log: select.log (continues run_select.sh's).
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/select.log
S="$TEMP/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad"
export STUDY_SPACING=5 STUDY_SPACING_emerald=3 STUDY_TIMEOUT=2400
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
rescore() { local f="$O/$1/$2/c.corr.json"; if [ -f "$f" ] && ! grep -q color_rb "$f"; then mv "$f" "$O/$1/$2/c.corr.v2.json"; fi; }
echo "[$(date +%H:%M:%S)] post start" >> $LOG
./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target VolumetricReSTIR > "$S/build_post.log" 2>&1
echo "build $?" | tee -a $LOG
bash outputs/mask_check.sh raw none 2>&1 | tail -1 | tee -a $LOG
SEL="VR_MUTATIONS=5 VR_MUT_STRAT=select VR_MUT_STATS=1"
ALL="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select VR_MUT_STATS=1"
POST="VR_MUT_AFTER_SPATIAL=1"
for L in bunnyparty bunnyrgb; do
    run $L mut5_select_post $SEL $POST
    run $L mcap_50_mut5_all_post VR_MTHRESH=50 $ALL $POST
    run $L dec_mcap_200_mut5_all_post VR_DECOUPLED=1 VR_MTHRESH=200 $ALL $POST
done
export STUDY_TIMEOUT=7200
for L in plume_g-0.9 emerald bistro; do
    for c in noreuse shipped mcap_50 dec_mcap_200; do rescore $L $c; done
    run $L noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
    run $L shipped
    run $L mut5_all $ALL
    run $L mcap_50 VR_MTHRESH=50
    run $L mcap_50_mut5_all VR_MTHRESH=50 $ALL
    run $L dec_mcap_200 VR_DECOUPLED=1 VR_MTHRESH=200
    run $L dec_mcap_200_mut5_all_post VR_DECOUPLED=1 VR_MTHRESH=200 $ALL $POST
done
echo "[$(date +%H:%M:%S)] post done" >> $LOG
