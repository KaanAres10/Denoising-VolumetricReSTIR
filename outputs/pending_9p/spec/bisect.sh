#!/bin/bash
# Which specialized field changes pixels? Bistro volume-only, 60 frames: VR_SPECIALIZE=0 once, then
# one capture per VR_SPECIALIZE_FIELDS mask, each compared with it.   bisect.sh <mask> [<mask> ...]
R=/c/research/Denoising-VolumetricReSTIR; cd $R
O=outputs/pending_9p/spec/bisect; mkdir -p $O
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
cap() { # $1 tag  $2.. env
  local tag=$1; shift
  ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
    for kv in "$@"; do export "$kv"; done
    rm -rf $O/$tag; mkdir -p $O/$tag
    VR_USE_SURFACE=0 VR_SCENE=bistro VR_FRAMES=60 VR_WARM=30 VR_DISPLAY=1920x1080 VR_DENOISER=none VR_OUT_DIR="C:/research/Denoising-VolumetricReSTIR/$O/$tag" VR_TAG=p \
      timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\capture_orbit.py" > $O/$tag/run.log 2>&1 )
}
[ -d $O/off ] && [ $(ls $O/off/*.png 2>/dev/null | wc -l) = 60 ] || cap off VR_SPECIALIZE=0
for m in "$@"; do
  cap m_$m VR_SPECIALIZE_FIELDS=$m
  python - "$O/off" "$O/m_$m" "$m" <<'PY'
import glob, os, sys, numpy as np
from PIL import Image
a, b, m = sys.argv[1:4]
n = sorted(set(map(os.path.basename, glob.glob(a + "/*.png"))) & set(map(os.path.basename, glob.glob(b + "/*.png"))))
same = 0; mx = 0
for f in n:
    x = np.asarray(Image.open(a + "/" + f)).astype(int); y = np.asarray(Image.open(b + "/" + f)).astype(int)
    d = np.abs(x - y)[..., :3].max(); same += d == 0; mx = max(mx, d)
print("mask %s: frames %d, byte-identical %d, max diff %d" % (m, len(n), same, mx))
PY
done
echo BISECT DONE
