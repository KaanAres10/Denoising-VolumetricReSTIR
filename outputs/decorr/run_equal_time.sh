#!/bin/bash
# Equal time (the paper's Fig. 7 question; spec V-B5 found more candidates win on bistro): per first-round scene and
# bounce count, plain ReSTIR given the time 5 mutations cost, spent on more initial candidates (the count from
# run_cost.sh via cost_table.py --json, rounded), through OptiX at M cap 200 like the den_optix_mut{0,5}cap200 pair it
# joins (same chains, spacing and seeds, so the same two frames are kept). Scored by equal_time_table.py. Log: eqtime.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/eqtime.log
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
python $O/cost_table.py $O --json $O/cost/equal_time.json > /dev/null || exit 1
count() { python -c "
import json, sys
r = {x['label']: x for x in json.load(open('$O/cost/equal_time.json'))}.get(sys.argv[1])
k = r and r['equal_time_candidates_5']
print(int(round(k)) if k else 32)" "$1"; }
export STUDY_SPACING=5
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
echo "[$(date +%H:%M:%S)] equal time start" >> $LOG
for L in explosiondusk bunnycathedral_d0.3 bunnyback_g0.8 bunnysoftbox wdassunset_g0.85 \
         explosiondusk_b2 bunnycathedral_d0.3_b2 bunnyback_g0.8_b2 bunnysoftbox_b2 wdassunset_g0.85_b2; do
    # The pairs' chain counts: 10, except the two-bounce scenes after the explosion (run_two_bounce.sh: 4).
    case $L in *_b2) [ "$L" = explosiondusk_b2 ] && export STUDY_CHAINS=10 || export STUDY_CHAINS=4 ;; *) export STUDY_CHAINS=10 ;; esac
    export STUDY_TIMEOUT=21600
    k=$(count "$L")
    bash $O/run_cost.sh "$L" "$k"  # its measured cost, next to the 5 mutations' (cost.log)
    echo "[$(date +%H:%M:%S)] $L: equal time to 5 mutations = $k initial candidates: $(python -c "
import json; f = lambda c: json.load(open('$O/cost/$L/%s/c.passes.json' % c))['/onFrameRender/RenderGraphExe::execute()/VolumetricReSTIR/gpu_time']['median']
print('%.1f ms vs 5 mutations %.1f ms' % (f('im$k'), f('mut5')))")" >> $LOG
    # shellcheck disable=SC2086
    run $L den_optix_eq5cap200 VR_DENOISER=optix $LOOK VR_MTHRESH=200 VR_INITIAL_M=$k
done
echo "[$(date +%H:%M:%S)] equal time done" >> $LOG
