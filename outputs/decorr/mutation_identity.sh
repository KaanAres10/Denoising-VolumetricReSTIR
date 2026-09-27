#!/bin/bash
# Byte-identity of mutation-pass configurations that must not change the image (plan Tasks 8-9): renders
# plume and bistro with the given environment and compares every capture, byte for byte, with a render
# that sets none of it. Short chains at 640x360 -- identity, not statistics.
#
#   mutation_identity.sh <tag> VAR=value...   e.g.  mutation_identity.sh mut1 VR_MUTATIONS=1
#                                                   mutation_identity.sh nostrat VR_MUTATIONS=4 VR_MUT_STRAT=
# Prints one line per scene: "<scene> <tag>: N captures, M byte-identical". Exit 1 unless all are identical.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
SCRIPT='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py'
OUT=${ID_OUT:-.superpowers/sdd/2026-09-27-restir-mcmc-decorrelation/identity}
tag=$1
shift

render() {  # dir, then env assignments
    local d=$1
    shift
    rm -rf "$d"
    mkdir -p "$d"
    (
        for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
        export VR_DISPLAY=640x360 VR_CHAINS=2 VR_PER_CHAIN=3 VR_WARM=40 VR_SPACING=5 VR_IDS=0 "$@"
        VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 1800 "$MOG" --script "$SCRIPT" > "$d/run.log" 2>&1
    )
}

status=0
for scene in plume bistro; do
    [ -f "$OUT/$scene/off/c.schedule.json" ] || render "$OUT/$scene/off" VR_SCENE=$scene
    render "$OUT/$scene/$tag" VR_SCENE=$scene "$@"
    n=0
    same=0
    for f in "$OUT/$scene/off"/*.exr; do
        n=$((n + 1))
        cmp -s "$f" "$OUT/$scene/$tag/$(basename "$f")" && same=$((same + 1))
    done
    echo "$scene $tag: $n captures, $same byte-identical"
    grep -q "(Error)" "$OUT/$scene/$tag/run.log" && { echo "  errors in $OUT/$scene/$tag/run.log"; status=1; }
    [ "$n" -gt 0 ] && [ "$n" -eq "$same" ] || status=1
done
exit $status
