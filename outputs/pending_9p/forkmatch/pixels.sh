#!/bin/bash
# Which volume-only captures the fork-parity fixes change: plume and bistro volume-only, 60 frames, with the
# fixes compiled out (VR_PRE_FORK_PARITY=1) against the default.   pixels.sh
R=/c/research/Denoising-VolumetricReSTIR; cd $R
O=outputs/pending_9p/forkmatch/pixels; rm -rf $O; mkdir -p $O
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
cap() { # tag scene surface(0 or empty) slang-args
  ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
    [ -n "$3" ] && export VR_USE_SURFACE=$3
    [ -n "$4" ] && export VR_SLANG_ARGS="$4"
    mkdir -p $O/$1
    VR_SCENE=$2 VR_FRAMES=60 VR_WARM=30 VR_DISPLAY=1920x1080 VR_DENOISER=none VR_OUT_DIR="C:/research/Denoising-VolumetricReSTIR/$O/$1" VR_TAG=p \
      timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\capture_orbit.py" > $O/$1/run.log 2>&1 )
}
for s in plume bvol; do
  sc=bistro; surf=0; [ $s = plume ] && { sc=plume; surf=""; }
  cap ${s}_pre $sc "$surf" "-DVR_PRE_FORK_PARITY=1"; cap ${s}_fixed $sc "$surf" ""
done
python - "$O" plume bvol <<'PY'
import glob, os, sys, numpy as np
from PIL import Image
O = sys.argv[1]
for s in sys.argv[2:]:
    a, b = O + "/" + s + "_pre", O + "/" + s + "_fixed"
    n = sorted(set(map(os.path.basename, glob.glob(a + "/*.png"))) & set(map(os.path.basename, glob.glob(b + "/*.png"))))
    same = 0; fr = []; ma = mb = 0
    for f in n:
        x = np.asarray(Image.open(a + "/" + f))[..., :3].astype(int); y = np.asarray(Image.open(b + "/" + f))[..., :3].astype(int)
        d = np.abs(x - y).max(-1); same += d.max() == 0; fr.append((d > 0).mean() * 100); ma += x.mean(); mb += y.mean()
    print("%s: frames %d, byte-identical %d, differing pixels up to %.2f%%, mean %.3f -> %.3f" % (s, len(n), same, max(fr) if fr else 0, ma / max(len(n), 1), mb / max(len(n), 1)))
PY
echo PIXELS DONE
