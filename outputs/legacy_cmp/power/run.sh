#!/bin/bash
# GPU clock / power / throttle reasons logged every 200 ms while one engine renders bistro volume-only
# (300 frames, the wall-clock setup).   run.sh <tag> <legacy|v9> [ENV=VAL ...]
tag=$1; eng=$2; shift 2
R=/c/research/Denoising-VolumetricReSTIR; O=$R/outputs/legacy_cmp/power; cd $R
nvidia-smi --query-gpu=timestamp,clocks.gr,clocks.mem,power.draw,temperature.gpu,clocks_throttle_reasons.active --format=csv,noheader -lms 200 > $O/$tag.smi.csv &
SMI=$!
( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
  for kv in "$@"; do export "$kv"; done
  if [ $eng = legacy ]; then
    cd legacy && VR_NO_SURFACE=1 VR_FRAMES=300 VR_RESULT="$(cygpath -m $O)/$tag.txt" timeout 900 ./Bin/x64/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\legacy\Scripts\_time_raw_legacy.py" > $O/$tag.log 2>&1
  else
    VR_USE_SURFACE=0 VR_FRAMES=300 VR_ENGINE=v9 VR_RESULT="$(cygpath -m $O)/$tag.txt" timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py" > $O/$tag.log 2>&1
  fi )
kill $SMI 2>/dev/null
python - $O/$tag.smi.csv $O/$tag.txt $tag <<'PY'
import sys, csv, statistics as st
rows = [r for r in csv.reader(open(sys.argv[1])) if len(r) >= 6]
busy = [r for r in rows if float(r[3].split()[0]) > 40]   # frames rendering (power above idle)
clk = [float(r[1].split()[0]) for r in busy]; pw = [float(r[3].split()[0]) for r in busy]
res = open(sys.argv[2]).readline().strip() if __import__("os").path.exists(sys.argv[2]) else "no result"
print("%-12s samples %3d  gr clock median %4.0f MHz  power median %5.1f W  | %s" % (sys.argv[3], len(busy), st.median(clk) if clk else 0, st.median(pw) if pw else 0, res))
PY
