#!/bin/bash
# Byte-identity of VR_SPECIALIZE (sampling options compiled in as constants): plume and bistro
# volume-only, 60 frames, with VR_SPECIALIZE=0 against the default; then bistro raw 300 frames against
# the locked rb_v9p_raw.   verify.sh [quick]  (quick: bistro volume-only only)
R=/c/research/Denoising-VolumetricReSTIR; cd $R
O=outputs/pending_9p/spec/verify; rm -rf $O; mkdir -p $O
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
cap() { # $1 tag  $2 scene  $3 surface(0/1 or empty)  $4 VR_SPECIALIZE value (empty = default)
  ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
    [ -n "$3" ] && export VR_USE_SURFACE=$3
    [ -n "$4" ] && export VR_SPECIALIZE=$4
    mkdir -p $O/$1
    VR_SCENE=$2 VR_FRAMES=60 VR_WARM=30 VR_DISPLAY=1920x1080 VR_DENOISER=none VR_OUT_DIR="C:/research/Denoising-VolumetricReSTIR/$O/$1" VR_TAG=p \
      timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\capture_orbit.py" > $O/$1/run.log 2>&1 )
  echo "$1: $(ls $O/$1/*.png 2>/dev/null | wc -l) frames"
}
scenes="bvol"; [ "$1" = quick ] || scenes="bvol plume"
for s in $scenes; do
  sc=bistro; surf=0; [ $s = plume ] && { sc=plume; surf=""; }
  cap ${s}_off $sc "$surf" 0; cap ${s}_on $sc "$surf" ""
done
python - "$O" $scenes <<'PY'
import glob, os, sys, numpy as np
from PIL import Image
O = sys.argv[1]
for s in sys.argv[2:]:
    a, b = O + "/" + s + "_off", O + "/" + s + "_on"
    n = sorted(set(map(os.path.basename, glob.glob(a + "/*.png"))) & set(map(os.path.basename, glob.glob(b + "/*.png"))))
    same = 0; fr = []; mx = 0
    for f in n:
        x = np.asarray(Image.open(a + "/" + f)).astype(int); y = np.asarray(Image.open(b + "/" + f)).astype(int)
        d = np.abs(x - y)[..., :3].max(-1); same += d.max() == 0; fr.append((d > 0).mean() * 100); mx = max(mx, d.max())
    print("%s: frames compared %d, byte-identical %d, differing pixels up to %.3f%%, max %d" % (s, len(n), same, max(fr) if fr else 0, mx))
PY
[ "$1" = quick ] || { bash outputs/mask_check.sh raw none 2>&1 | tail -1; bash outputs/mask_check.sh relax nrd RelaxDiffuseSh 2>&1 | tail -1; bash outputs/mask_check.sh rr rr 2>&1 | tail -1; }
echo VERIFY DONE
