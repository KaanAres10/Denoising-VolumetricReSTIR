#!/bin/bash
# Byte-identity of DXC 1.8 vs 1.7 (the compiler Falcor 9 ships): plume and bistro volume-only, 60 frames,
# captured with each compiler; bistro raw 300 frames with DXC 1.8 against the locked rb_v9p_raw.
# The gfx shader cache is moved aside for the whole run (every capture compiles fresh; its keys do cover the compiler).
R=/c/research/Denoising-VolumetricReSTIR; cd $R
B=build/windows-vs2022/bin/Release; D=outputs/pending_9p/dxc; O=$D/verify; rm -rf $O; mkdir -p $O
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
[ -d $B/.shadercache ] && mv $B/.shadercache $B/.shadercache_keep
restore() { rm -rf $B/.shadercache; [ -d $B/.shadercache_keep ] && mv $B/.shadercache_keep $B/.shadercache; cp -p $D/dxc17/* $B/; }
trap restore EXIT
cap() { # $1 tag $2 scene $3 surface
  ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
    [ -n "$3" ] && export VR_USE_SURFACE=$3
    mkdir -p $O/$1
    VR_SCENE=$2 VR_FRAMES=60 VR_WARM=30 VR_DISPLAY=1920x1080 VR_DENOISER=none VR_OUT_DIR="C:/research/Denoising-VolumetricReSTIR/$O/$1" VR_TAG=p \
      timeout 900 ./$B/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\capture_orbit.py" > $O/$1/run.log 2>&1 )
  echo "$1: $(ls $O/$1/*.png 2>/dev/null | wc -l) frames"
}
cp -p $D/dxc17/* $B/; rm -rf $B/.shadercache; cap plume_17 plume ""; cap bvol_17 bistro 0
cp -p $D/dxc18/* $B/; rm -rf $B/.shadercache; cap plume_18 plume ""; cap bvol_18 bistro 0
python - "$O" <<'PY'
import hashlib, glob, os, sys
O = sys.argv[1]; h = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
for s in ("plume", "bvol"):
    a, b = O + "/" + s + "_17", O + "/" + s + "_18"
    names = sorted(set(map(os.path.basename, glob.glob(a + "/*.png"))) & set(map(os.path.basename, glob.glob(b + "/*.png"))))
    print("%s: frames compared %d, byte-identical %d" % (s, len(names), sum(1 for n in names if h(a + "/" + n) == h(b + "/" + n))))
PY
rm -rf $B/.shadercache; md5sum $B/dxcompiler.dll | cut -c1-8; bash outputs/mask_check.sh raw none 2>&1 | tail -1
echo VERIFY_DXC DONE
