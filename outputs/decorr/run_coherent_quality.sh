#!/bin/bash
# Stage 2's quality check (user, 2026-10-06: "faster while keeping visual quality same"; the coherent move choice
# changes the images, unlike Stage 1). 1) Bias: the explosion's two bounces, 5 moves of every kind with
# VR_MUT_COHERENT=1, on run_b2_bias_paired.sh's 64 chains and seeds (480x270), paired against its plain and per-pixel
# runs -- their chain means from chains.json, their EXRs being gone -- and against the reference. 2) Denoised: per
# first-round scene at 1 and 2 bounces, den_optix_mut5cohcap200 -- den_optix_mut5cap200 with the switch on (same
# chains, spacing, seeds and kept frames) -- scored by equal_time_table.py --configs. Log: coherent.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/coherent.log
SCRIPT_CP='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
echo "[$(date +%H:%M:%S)] coherent start" >> $LOG

B="$R/$O/b2bias_paired/explosiondusk_b2"
d="$B/mut5_all_coherent"
if [ ! -f "$R/$O/b2bias_paired/chains_coherent.json" ]; then
    mkdir -p "$d"
    # shellcheck disable=SC2046
    ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
      export VR_SCENE=explosiondusk VR_MAX_BOUNCES=2 VR_DISPLAY=480x270 VR_CHAINS=64 VR_PER_CHAIN=12 VR_SPACING=4 \
             VR_WARM=800 VR_IDS=0 VR_MTHRESH=200 VR_SEED_BASE=1000000 VR_MUTATIONS=5 VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1 \
             VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce VR_MUT_COHERENT=1
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 10800 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
    echo "[$(date +%H:%M:%S)] bias run: $(ls "$d"/*.exr 2>/dev/null | wc -l) exr $(grep -c '(Error)' "$d/run.log") errors" >> $LOG
    REF=$(ls "$B"/ref/c.Accum.output.*.exr | sort -t. -k4 -n | tail -1)
    python $O/bias_check.py "$B" mcap200 mut5_all mut5_all_coherent --paired --saved "$B/chains.json" --ref "$REF" \
        --save "$R/$O/b2bias_paired/chains_coherent.json" 2>&1 | sed "s/^/bias (paired) explosiondusk_b2: /" | tee -a $LOG
    grep -h "mutations, last 256\|bounce moves" "$d/run.log" | tail -2 | sed "s/^/bias run stats: /" >> $LOG
    rm -f /c/research/Denoising-VolumetricReSTIR/outputs/decorr/b2bias_paired/explosiondusk_b2/mut5_all_coherent/c.*.exr
fi

export STUDY_SPACING=5 STUDY_TIMEOUT=21600
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
for L in explosiondusk bunnycathedral_d0.3 bunnyback_g0.8 bunnysoftbox wdassunset_g0.85 \
         explosiondusk_b2 bunnycathedral_d0.3_b2 bunnyback_g0.8_b2 bunnysoftbox_b2 wdassunset_g0.85_b2; do
    # The pairs' chain counts: 10, except the two-bounce scenes after the explosion (run_two_bounce.sh: 4).
    case $L in *_b2) [ "$L" = explosiondusk_b2 ] && export STUDY_CHAINS=10 || export STUDY_CHAINS=4 ;; *) export STUDY_CHAINS=10 ;; esac
    S=light,depth,select,flight
    case $L in *_b2) S=$S,direction,distance,rebounce ;; esac
    # shellcheck disable=SC2086
    run $L den_optix_mut5cohcap200 VR_DENOISER=optix $LOOK VR_MTHRESH=200 VR_MUTATIONS=5 VR_MUT_STRAT=$S VR_MUT_STATS=1 \
        VR_MUT_AFTER_SPATIAL=1 VR_MUT_COHERENT=1
done
python $O/equal_time_table.py $O --configs den_optix_mut0cap200,den_optix_mut5cap200,den_optix_mut5cohcap200 2>&1 | tee -a $LOG
echo "[$(date +%H:%M:%S)] coherent done" >> $LOG
