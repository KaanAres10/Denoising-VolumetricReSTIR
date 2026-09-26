#!/bin/bash
# How much VR_FP_MODE_VOLUME=fast changes the image: plume and bistro volume-only, 60 frames, precise
# (default) against fast; per-frame share of differing pixels, max and mean abs difference, PSNR.
R=/c/research/Denoising-VolumetricReSTIR; cd $R
O=outputs/pending_9p/fastmath/cap; rm -rf $O; mkdir -p $O
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
cap() { # $1 tag $2 scene $3 surface $4 fp mode (empty = default)
  ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
    [ -n "$3" ] && export VR_USE_SURFACE=$3
    [ -n "$4" ] && export VR_FP_MODE_VOLUME=$4
    mkdir -p $O/$1
    VR_SCENE=$2 VR_FRAMES=60 VR_WARM=30 VR_DISPLAY=1920x1080 VR_DENOISER=none VR_OUT_DIR="C:/research/Denoising-VolumetricReSTIR/$O/$1" VR_TAG=p \
      timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\capture_orbit.py" > $O/$1/run.log 2>&1 )
}
cap plume_precise plume "" ""; cap plume_fast plume "" fast; cap bvol_precise bistro 0 ""; cap bvol_fast bistro 0 fast
python - "$O" <<'PY'
import glob, os, sys, numpy as np
from PIL import Image
O = sys.argv[1]
for s in ("plume", "bvol"):
    a, b = O + "/" + s + "_precise", O + "/" + s + "_fast"
    n = sorted(set(map(os.path.basename, glob.glob(a + "/*.png"))) & set(map(os.path.basename, glob.glob(b + "/*.png"))))
    frac, mx, mad, psnr, lit = [], 0, [], [], []
    for f in n:
        x = np.asarray(Image.open(a + "/" + f)).astype(float)[..., :3]; y = np.asarray(Image.open(b + "/" + f)).astype(float)[..., :3]
        d = np.abs(x - y); dm = d.max(-1)
        frac.append((dm > 0).mean() * 100); mx = max(mx, dm.max()); mad.append(d.mean())
        mse = (d ** 2).mean(); psnr.append(99.0 if mse == 0 else 10 * np.log10(255 ** 2 / mse))
        lit.append((x.max(-1) > 0).mean() * 100)
    print("%s: %d frames | pixels differing %.3f%% median (%.3f-%.3f%%) | max diff %d/255 | mean abs diff %.4f/255 | PSNR median %.1f dB (min %.1f) | lit pixels %.0f%%"
          % (s, len(n), np.median(frac), min(frac), max(frac), mx, np.mean(mad), np.median(psnr), min(psnr), np.mean(lit)))
    # histogram of differences over all frames
PY
echo DIFF DONE
