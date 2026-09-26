#!/bin/bash
# Byte-identity of the unrolled per-sample loops in SampleMediumAnalyticAdapterGVDB:
#   plume (volume-only, environment light) and bistro volume-only: HEAD's shaders vs the new ones,
#   60 frames each; bistro raw full scene: 300 frames vs the locked rb_v9p_raw (mask_check.sh).
R=/c/research/Denoising-VolumetricReSTIR; cd $R
S=build/windows-vs2022/bin/Release/shaders/RenderPasses/VolumetricReSTIR
FILES="VolumeTrackingAdapterGVDB.slang"
O=outputs/pending_9p/unroll/verify; rm -rf $O; mkdir -p $O/newsh
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
cap() { # $1 tag  $2 scene  $3 surface(0/1 or empty)
  ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
    [ -n "$3" ] && export VR_USE_SURFACE=$3
    mkdir -p $O/$1
    VR_SCENE=$2 VR_FRAMES=60 VR_WARM=30 VR_DISPLAY=1920x1080 VR_DENOISER=none VR_OUT_DIR="C:/research/Denoising-VolumetricReSTIR/$O/$1" VR_TAG=p \
      timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\capture_orbit.py" > $O/$1/run.log 2>&1 )
  echo "$1: $(ls $O/$1/*.png 2>/dev/null | wc -l) frames"
}
for f in $FILES; do cp -p $S/$f $O/newsh/$f; git show HEAD:Source/RenderPasses/VolumetricReSTIR/$f > $S/$f; done
cap plume_old plume ""; cap bvol_old bistro 0
for f in $FILES; do cp -p $O/newsh/$f $S/$f; cmp -s $S/$f Source/RenderPasses/VolumetricReSTIR/$f || echo "RESTORE MISMATCH $f"; done
cap plume_new plume ""; cap bvol_new bistro 0
python - "$O" <<'PY'
import hashlib, glob, os, sys
O = sys.argv[1]
h = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
for s in ("plume", "bvol"):
    a, b = O + "/" + s + "_old", O + "/" + s + "_new"
    names = sorted(set(map(os.path.basename, glob.glob(a + "/*.png"))) & set(map(os.path.basename, glob.glob(b + "/*.png"))))
    print("%s: frames compared %d, byte-identical %d" % (s, len(names), sum(1 for n in names if h(a + "/" + n) == h(b + "/" + n))))
PY
bash outputs/mask_check.sh raw none 2>&1 | tail -1
echo VERIFY DONE
