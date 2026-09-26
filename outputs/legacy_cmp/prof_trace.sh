#!/bin/bash
# 9.0 volume-only shader-profiler trace at the pose of outputs/gputrace_sp (VR_FRAMES=80, frame 61),
# with extra environment settings.  prof_trace.sh <tag> [ENV=VAL ...]
tag="$1"; shift
NG="/c/Program Files/NVIDIA Corporation/Nsight Graphics 2026.2.0/host/windows-desktop-nomad-x64/ngfx.exe"
R=/c/research/Denoising-VolumetricReSTIR
O=$R/outputs/gputrace_sp/prof_$tag; rm -rf "$O"; mkdir -p "$O"
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
(
  for e in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $e; done
  for kv in "$@"; do export "$kv"; done
  cd $R && VR_USE_SURFACE=0 VR_FRAMES=80 VR_ENGINE=v9 timeout 900 "$NG" --activity "GPU Trace Profiler" \
    --exe "C:\research\Denoising-VolumetricReSTIR\build\windows-vs2022\bin\Release\Mogwai.exe" --dir "C:\research\Denoising-VolumetricReSTIR" \
    --args "--script C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py" \
    --start-after-frames 60 --limit-to-frames 1 --real-time-shader-profiler --auto-export --output-dir "$(cygpath -m $O)" > "$O/ngfx.log" 2>&1
)
ls "$O"/*.ngfx-gputrace 2>/dev/null | head -1 || echo "$tag: NO TRACE"
