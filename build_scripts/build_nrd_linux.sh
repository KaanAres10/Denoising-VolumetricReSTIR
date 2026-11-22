#!/bin/sh

# Builds libNRD.so for Linux into external/nrd-4/Lib/Release. external/nrd-4 is git-ignored and vendored by hand: its Include and
# Shaders (which carry local patches, see Source/RenderPasses/NRDPass/README.md) must already be there, and the library must come
# from the same tag. Falcor compiles NRD's shaders itself, so none are embedded in the library.
#
#   $1 -> cmake to use (optional). NRD needs 3.30 or newer, which is newer than Falcor's packman CMake and Ubuntu 24.04's.

set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
TAG=v4.17.3
CMAKE=${1:-cmake}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

if ! grep -q "NRD_VERSION_MINOR 17" "$ROOT/external/nrd-4/Include/NRD.h"; then
    echo "external/nrd-4/Include/NRD.h is not NRD 4.17; update TAG in $0 to match it."
    exit 1
fi

git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$TAG" https://github.com/NVIDIA-RTX/NRD "$WORK/NRD"
"$CMAKE" -S "$WORK/NRD" -B "$WORK/build" -DCMAKE_BUILD_TYPE=Release \
    -DNRD_EMBEDS_SPIRV_SHADERS=OFF -DNRD_EMBEDS_DXIL_SHADERS=OFF -DNRD_EMBEDS_DXBC_SHADERS=OFF
"$CMAKE" --build "$WORK/build" --config Release --target NRD -j "$(nproc)"

LIB=$(find "$WORK" -name 'libNRD.so' | head -1)
if [ -z "$LIB" ]; then
    echo "libNRD.so was not produced."
    exit 1
fi
mkdir -p "$ROOT/external/nrd-4/Lib/Release"
cp -f "$LIB" "$ROOT/external/nrd-4/Lib/Release/libNRD.so"
echo "Built $ROOT/external/nrd-4/Lib/Release/libNRD.so from $TAG"
