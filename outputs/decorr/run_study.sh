#!/bin/bash
# The decorrelation study's runs (docs/superpowers/plans/2026-09-27-restir-mcmc-decorrelation.md).
#
#   run_study.sh survey [labels...]   no reuse vs as shipped, on every scene (or the labels given)
#   run_study.sh burst [labels...]    consecutive frames for the temporal autocorrelation, as shipped
#   run_study.sh deep <label>         one factor at a time around as shipped
#   run_study.sh refs <label>         a path-traced reference (not bistro: forkref's v9sa_ref is used)
#   run_study.sh denoise <label> [N]  every denoiser, as shipped vs no reuse, at the still pose; with N,
#                                     as shipped + N mutations instead (den_<denoiser>_mutN)
#   run_study.sh one <label> <config> [VAR=value...]   a single config (e.g. equal-time runs)
#   run_study.sh mutate1 [labels...]  one mutation (light + depth) on every scene (or the labels given)
#   run_study.sh mutate <label>       Phase B: mutations 1 and 5 x strategy light / depth / both, and one
#                                     mutation at M caps 10 / 50 / 200 (the shipped cap is mut1_both)
#   run_study.sh summary              outputs/decorr/summary.tsv and every scene's sheet.png
#
# A label is a vr_graph scene, optionally with a phase-function g and a density multiplier:
# plume_g-0.9 = VR_SCENE=plume VR_PHASE_G=-0.9, wdas_d0.2 = VR_SCENE=wdas VR_DENSITY_MULT=0.2. Each config
# lands in outputs/decorr/<label>/<config>/, is scored by m_corr.py (against the label's noreuse run and
# reference when they exist), then pruned to a few frames by prune.py. Scoring runs on the CPU while the
# next config renders on the GPU; one scoring at a time, in order. A config that already has c.corr.json
# is skipped, so an interrupted run resumes.
#
# STUDY_DISPLAY=WxH (default 1920x1080), STUDY_CHAINS, STUDY_PER_CHAIN, STUDY_WARM override the harness
# defaults; STUDY_SPACING sets the capture spacing for every label, STUDY_SPACING_<label> for one (dashes
# and dots in the label become underscores: STUDY_SPACING_plume_g_0_9).
# STUDY_TIMEOUT (seconds, default 14400) bounds one Mogwai run: a Falcor error dialog otherwise holds the
# queue until the timeout.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
T=outputs/decorr             # the tools
O="${STUDY_OUT:-outputs/decorr}"  # the runs (STUDY_OUT for a dry run elsewhere)
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
SCRIPT='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
ALL="plume plume_g-0.9 bistro explosion emerald bunny bunny_g0.8 wdas"
BISTRO_REF=outputs/pending_9p/forkref/cap/v9sa_ref/v9sa_ref.Accum.output.8191.exr
# The Look configuration the locked denoiser table uses (memory: falcor9-port-rebaseline).
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"

if tasklist 2>/dev/null | grep -qi mogwai; then echo "[study] Mogwai is running; abort"; exit 1; fi
ls build/windows-vs2022/bin/Release/libprotoc.dll build/windows-vs2022/bin/Release/z.dll >/dev/null 2>&1 ||
    ./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target restore_runtime_dlls >/dev/null 2>&1

scene_env() {  # label -> VR_SCENE (+ VR_PHASE_G for _g<g>, VR_DENSITY_MULT for _d<mult>, VR_MAX_BOUNCES for _b<n>)
    local IFS=_
    # shellcheck disable=SC2086
    set -- $1
    local out="VR_SCENE=$1" m
    shift
    for m in "$@"; do
        case "$m" in
            g*) out="$out VR_PHASE_G=${m#g}" ;;
            d*) out="$out VR_DENSITY_MULT=${m#d}" ;;
            b*) out="$out VR_MAX_BOUNCES=${m#b}" ;;
        esac
    done
    echo "$out"
}

spacing_for() {
    local key="STUDY_SPACING_$(echo "$1" | tr -- '-.' '__')"
    echo "${!key:-${STUDY_SPACING:-33}}"
}

ref_for() {  # the label's converged reference, or nothing
    if [ "$1" = bistro ]; then [ -f "$BISTRO_REF" ] && echo "$BISTRO_REF"; return; fi
    local s="$O/$1/ref/c.schedule.json"
    [ -f "$s" ] || return
    local f
    f=$(python -c "import json; print(json.load(open('$s'))['reference_frames'][-1])")
    [ -f "$O/$1/ref/c.Accum.output.$f.exr" ] && echo "$O/$1/ref/c.Accum.output.$f.exr"
}

render() {  # dir, then env assignments; runs correlation_pose.py into dir
    local d=$1
    shift
    mkdir -p "$d"
    (
        for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
        # STUDY_MUT_COHERENT=0: mutations draw a move kind per pixel, as every run before 2af014f did (the pass draws
        # one per step for the whole frame by default since then); a config's own VR_MUT_COHERENT still wins.
        [ -n "${STUDY_MUT_COHERENT:-}" ] && export VR_MUT_COHERENT="$STUDY_MUT_COHERENT"
        # shellcheck disable=SC2046
        export VR_DISPLAY="${STUDY_DISPLAY:-1920x1080}" "$@"
        [ -n "${STUDY_CHAINS:-}" ] && export VR_CHAINS="$STUDY_CHAINS"
        [ -n "${STUDY_PER_CHAIN:-}" ] && export VR_PER_CHAIN="$STUDY_PER_CHAIN"
        [ -n "${STUDY_WARM:-}" ] && export VR_WARM="$STUDY_WARM"
        VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout "${STUDY_TIMEOUT:-14400}" "$MOG" --script "$SCRIPT" > "$d/run.log" 2>&1
    )
}

SCORING=  # pid of the previous config's scoring, which overlaps this config's render

finish_scoring() {
    if [ -n "$SCORING" ]; then wait "$SCORING"; SCORING=; fi
}

cap() {  # label config [env assignments...]
    local label=$1 cfg=$2
    shift 2
    local d="$O/$label/$cfg"
    if [ -f "$d/c.corr.json" ]; then echo "[study] skip $label/$cfg"; return 0; fi
    # STUDY_SKIP_DEC=1: leave out the decoupled-history configs (dec_*, den_*dec*): mutations alone are compared.
    case "$cfg" in dec_*|den_*dec*) [ "${STUDY_SKIP_DEC:-0}" = 1 ] && { echo "[study] skip $label/$cfg (STUDY_SKIP_DEC)"; return 0; } ;; esac
    local t0=$SECONDS
    # shellcheck disable=SC2046
    render "$d" $(scene_env "$label") VR_SPACING="$(spacing_for "$label")" VR_IDS=1 "$@"
    if [ ! -f "$d/c.schedule.json" ] || grep -q "(Error)" "$d/run.log"; then
        echo "[study] FAILED $label/$cfg (see $d/run.log)"
        return 1
    fi
    # The previous config's scoring ends first: it can be this one's baseline (noreuse before shipped).
    finish_scoring
    score "$label" "$cfg" "$d" "$t0" &
    SCORING=$!
}

score() {  # label config dir t0: m_corr against the baseline and reference, then prune
    local label=$1 cfg=$2 d=$3 t0=$4
    local args=(--tag c)
    [ "$label" = bistro ] && args+=(--regions bistro --clamp 1)
    local base="$O/$label/noreuse/c.corr.json"
    case "$cfg" in den_*_shipped | den_*_mut*) base="$O/$label/${cfg%_*}_noreuse/c.corr.json" ;; esac
    [ "$cfg" != noreuse ] && [ "${cfg%_noreuse}" = "$cfg" ] && [ -f "$base" ] && args+=(--baseline "$base")
    local ref
    ref=$(ref_for "$label")
    [ -n "$ref" ] && args+=(--ref "$ref")
    if ! python "$T/m_corr.py" "$d" "${args[@]}" > "$d/metrics.log" 2>&1; then
        echo "[study] METRICS FAILED $label/$cfg (see $d/metrics.log)"
        return 1
    fi
    python "$T/prune.py" "$d" c > /dev/null
    echo "[study] $label/$cfg $((SECONDS - t0))s  $(tail -1 "$d/metrics.log")"
}

mcap_of() { case "${1%%_*}" in bistro|emerald) echo 10 ;; *) echo 4 ;; esac; }

stage=${1:-}
shift || true
case "$stage" in
    survey)
        for l in ${@:-$ALL}; do
            cap "$l" noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
            cap "$l" shipped
        done ;;
    burst)
        for l in ${@:-$ALL}; do cap "$l" burst VR_BURST=256 VR_CHAINS=2 VR_PER_CHAIN=2 VR_IDS=0; done ;;
    deep)
        l=$1
        cap "$l" noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
        cap "$l" shipped
        cap "$l" temporal_only VR_NO_SPATIAL=1
        cap "$l" spatial_only VR_NO_TEMPORAL=1
        for q in 1 4 10 20 50 200; do
            [ "$q" = "$(mcap_of "$l")" ] && continue  # that is `shipped`
            cap "$l" "mcap_$q" VR_MTHRESH="$q"
        done
        cap "$l" radius_3 VR_SR_RADIUS=3
        cap "$l" radius_30 VR_SR_RADIUS=30
        cap "$l" rounds_3 VR_SR_ROUNDS=3
        cap "$l" pixel_offsets VR_SLANG_ARGS=-DVR_SR_PER_PIXEL_OFFSETS=1 ;;
    refs)
        l=$1
        d="$O/$l/ref"
        if [ -f "$d/c.schedule.json" ]; then echo "[study] skip $l/ref"; exit 0; fi
        t0=$SECONDS
        # shellcheck disable=SC2046
        render "$d" $(scene_env "$l") VR_MODE=reference VR_FRAMES="${STUDY_REF_FRAMES:-4096}" VR_SPP="${STUDY_REF_SPP:-16}"
        echo "[study] $l/ref $((SECONDS - t0))s  $(ls "$d"/*.exr 2>/dev/null | wc -l) captures" ;;
    denoise)
        l=$1
        for spec in optix oidn nrd:RelaxDiffuseSh nrd:ReblurDiffuseSh rr; do
            mode=${spec%%:*}
            method=${spec#*:}
            name=$mode
            extra=()
            if [ "$mode" = nrd ]; then name="nrd_${method}"; extra=(VR_NRD_METHOD="$method"); fi
            if [ -n "${2:-}" ]; then
                # shellcheck disable=SC2086
                cap "$l" "den_${name}_mut$2" VR_DENOISER="$mode" "${extra[@]}" $LOOK VR_MUTATIONS="$2" VR_MUT_STRAT=light,depth
                continue
            fi
            # shellcheck disable=SC2086
            cap "$l" "den_${name}_noreuse" VR_DENOISER="$mode" "${extra[@]}" $LOOK VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
            # shellcheck disable=SC2086
            cap "$l" "den_${name}_shipped" VR_DENOISER="$mode" "${extra[@]}" $LOOK
        done ;;
    one)
        cap "$@" ;;
    mutate1)
        for l in ${@:-$ALL}; do cap "$l" mut1_both VR_MUTATIONS=1 VR_MUT_STRAT=light,depth VR_MUT_STATS=1; done ;;
    mutate)
        l=$1
        for n in 1 5; do
            for s in light depth both; do
                strat=$s
                [ "$s" = both ] && strat=light,depth
                cap "$l" "mut${n}_$s" VR_MUTATIONS=$n VR_MUT_STRAT=$strat VR_MUT_STATS=1
            done
        done
        for q in 10 50 200; do
            [ "$q" = "$(mcap_of "$l")" ] && continue  # that is mut1_both
            cap "$l" "mcap_${q}_mut1" VR_MTHRESH="$q" VR_MUTATIONS=1 VR_MUT_STRAT=light,depth VR_MUT_STATS=1
        done ;;
    summary)
        python "$T/summarize.py" "$O"
        for d in "$O"/*/; do
            ls "$d"*/c.corr.json >/dev/null 2>&1 && python "$T/sheet.py" "${d%/}"
        done ;;
    *)
        sed -n 2,27p "$0"
        exit 1 ;;
esac
finish_scoring
