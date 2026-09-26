#!/bin/bash
# The GVDB DDA clamp (gvdbDda.slang, kMaxTDel): (1) VR_PRE_DDA_CLAMP=1 with VR_PRE_FORK_PARITY=1 still gives
# the locked rb_v9p_raw byte for byte (mask_check.sh); (2) this build with the firefly instrumentation removed
# reproduces the instrumented build's v9fix_restir_long captures (frames 256, 512); (3) which volume-only
# captures change (plume, bistro volume-only, 60 frames, clamp vs VR_PRE_DDA_CLAMP=1); (4) cost, interleaved.
R=/c/research/Denoising-VolumetricReSTIR; cd $R
F=outputs/pending_9p/forkref
bash outputs/mask_check.sh raw none 2>&1 | tail -1
bash $F/run.sh v9 restir 512 16 v9fix_clean VR_CAPTURES=2 | tail -1
python - <<'PY'
import glob, hashlib, os, re
C = "outputs/pending_9p/forkref/cap"
h = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
def frames(tag):
    return {int(re.search(r"\.(\d+)\.exr$", p).group(1)): p for p in glob.glob(os.path.join(C, tag, "*.exr")) if ".accumulated_color." in p or ".Accum." in p}
a = {os.path.basename(p).split(".", 1)[1]: p for p in glob.glob(os.path.join(C, "v9fix_clean", "*.exr"))}
b = {os.path.basename(p).split(".", 1)[1]: p for p in glob.glob(os.path.join(C, "v9fix_restir_long", "*.exr"))}
common = sorted(set(a) & set(b))
print("clean build vs instrumented build: %d files compared, byte-identical %d" % (len(common), sum(h(a[k]) == h(b[k]) for k in common)))
PY
O=$R/$F/ddapix; rm -rf $O; mkdir -p $O
cap() { # tag scene surface slang-args
  ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
    [ -n "$3" ] && export VR_USE_SURFACE=$3; [ -n "$4" ] && export VR_SLANG_ARGS="$4"
    mkdir -p $O/$1
    VR_SCENE=$2 VR_FRAMES=60 VR_WARM=30 VR_DISPLAY=1920x1080 VR_DENOISER=none VR_OUT_DIR="$(cygpath -m $O/$1)" VR_TAG=p \
      timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\capture_orbit.py" > $O/$1.log 2>&1 )
}
for s in plume bvol; do sc=bistro; surf=0; [ $s = plume ] && { sc=plume; surf=""; }; cap ${s}_pre $sc "$surf" "-DVR_PRE_DDA_CLAMP=1"; cap ${s}_fix $sc "$surf" ""; done
python - $O <<'PY'
import glob, os, sys, numpy as np
from PIL import Image
O = sys.argv[1]
for s in ("plume", "bvol"):
    a, b = O + "/" + s + "_pre", O + "/" + s + "_fix"
    n = sorted(set(map(os.path.basename, glob.glob(a + "/*.png"))) & set(map(os.path.basename, glob.glob(b + "/*.png"))))
    same = sum(np.array_equal(np.asarray(Image.open(a + "/" + f)), np.asarray(Image.open(b + "/" + f))) for f in n)
    print("%s: frames %d, byte-identical %d" % (s, len(n), same))
PY
PRE="VR_SLANG_ARGS=-DVR_PRE_DDA_CLAMP=1"
bash outputs/pending_9p/hoist/ab_env.sh $F/ddaperf 2 "full_pre:1:$PRE" "full_fix:1:" "vol_pre:0:$PRE" "vol_fix:0:"
echo DDAVERIFY DONE
