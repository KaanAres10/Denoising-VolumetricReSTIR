#!/bin/bash
# Speed-up C, fewer mutations (user, 2026-10-07: "after that try C"): the pass's cost is linear in the count, the
# decorrelation is not. Per first-round scene at 1 and 2 bounces: 3 and 1 mutations of every kind (the pass's defaults
# now: coherent moves, early rejection), through OptiX at M cap 200 like den_optix_mut5cohcap200 (Stage 2's 5; same
# chains, spacing, seeds and kept frames) -- den_optix_mut{3,1}cohcap200 -- then their time (run_cost.sh's setup, the
# 5-mutation run timed again for an A/B in one session). Scored by equal_time_table.py --configs. Log: fewer.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/fewer.log
SCRIPT_CP='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
LABELS="explosiondusk bunnycathedral_d0.3 bunnyback_g0.8 bunnysoftbox wdassunset_g0.85 explosiondusk_b2 bunnycathedral_d0.3_b2 bunnyback_g0.8_b2 bunnysoftbox_b2 wdassunset_g0.85_b2"
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
strat() { case $1 in *_b2) echo light,depth,select,flight,direction,distance,rebounce ;; *) echo light,depth,select,flight ;; esac; }
echo "[$(date +%H:%M:%S)] fewer start" >> $LOG

# Time first (minutes): Mutate Samples and the whole pass at 1, 3 and 5 mutations, A B B A style (1 3 5 5 3 1).
scene_env() { bash -c 'eval "$(sed -n "/^scene_env()/,/^}/p" '"$O"'/run_study.sh)"; scene_env "$1"' _ "$1"; }
for L in $LABELS; do
    for v in 1a 3a 5a 5b 3b 1b; do
        d="$R/$O/fewer_cost/$L/mut$v"
        [ -f "$d/c.passes.json" ] && continue
        mkdir -p "$d"
        # shellcheck disable=SC2046
        ( for x in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$x"; done
          export $(scene_env "$L") VR_DISPLAY=1920x1080 VR_CHAINS=1 VR_PER_CHAIN=4 VR_SPACING=8 VR_WARM=192 VR_IDS=0 \
                 VR_MTHRESH=200 VR_PASS_TIMES=1 VR_MUTATIONS=${v%?} VR_MUT_STATS=0 VR_MUT_AFTER_SPATIAL=1 VR_MUT_STRAT=$(strat $L)
          VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 1200 $MOG --script "$SCRIPT_CP" > "$d/run.log" 2>&1 )
        echo "[$(date +%H:%M:%S)] fewer cost $L/mut$v: $([ -f "$d/c.passes.json" ] && echo ok || echo MISSING)" >> $LOG
    done
done

export STUDY_SPACING=5 STUDY_TIMEOUT=21600
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
for n in 3 1; do
    for L in $LABELS; do
        # The pairs' chain counts: 10, except the two-bounce scenes after the explosion (run_two_bounce.sh: 4).
        case $L in *_b2) [ "$L" = explosiondusk_b2 ] && export STUDY_CHAINS=10 || export STUDY_CHAINS=4 ;; *) export STUDY_CHAINS=10 ;; esac
        # shellcheck disable=SC2086
        run $L den_optix_mut${n}cohcap200 VR_DENOISER=optix $LOOK VR_MTHRESH=200 VR_MUTATIONS=$n VR_MUT_STRAT=$(strat $L) \
            VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1
    done
done
python $O/equal_time_table.py $O --configs den_optix_mut0cap200,den_optix_mut1cohcap200,den_optix_mut3cohcap200,den_optix_mut5cohcap200 2>&1 | tee -a $LOG
echo "[$(date +%H:%M:%S)] fewer done" >> $LOG
