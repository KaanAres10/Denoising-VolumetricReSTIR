#!/bin/bash
# Re-runs after the plume orbit fix (capture_orbit.py orbits the plume, not Bistro's street point):
#  1. denoisers.sh part B for plume only (precise vs fast math, 5 denoisers, 120 frames)
#  2. plume byte-identity of the toggleable changes, 60 frames each: VR_SPECIALIZE=0, VR_GROUP=8x8,
#     VR_HOIST_ATLAS=0 against the default build.
R=/c/research/Denoising-VolumetricReSTIR; cd $R
O=$R/outputs/pending_9p/fastmath/den/orbit_fixed; mkdir -p $O
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
SC='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts'
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
clean_env() { for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done; }
for den in "raw none RelaxDiffuseSh" "optix optix RelaxDiffuseSh" "relax nrd RelaxDiffuseSh" "reblur nrd ReblurDiffuseSh" "rr rr RelaxDiffuseSh"; do
  set -- $den
  for fp in precise fast; do
    d=plume_$1_$fp
    ( clean_env; [ $fp = fast ] && export VR_FP_MODE_VOLUME=fast
      mkdir -p $O/$d
      VR_SCENE=plume VR_FRAMES=120 VR_WARM=30 VR_DISPLAY=1920x1080 VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient \
        VR_DENOISER=$2 VR_NRD_METHOD=$3 VR_OUT_DIR="$(cygpath -m $O/$d)" VR_TAG=d timeout 1500 $MOG --script "$SC\capture_orbit.py" > $O/$d.log 2>&1 )
    python $R/outputs/pending_9p/fastmath/score.py $O/$d "plume $1 $fp"
    rm -rf $O/$d
  done
done
V=$R/outputs/pending_9p/fastmath/plume_identity; rm -rf $V; mkdir -p $V
cap() { # tag ENV=VAL (or "")
  ( clean_env; [ -n "$2" ] && export "$2"; mkdir -p $V/$1
    VR_SCENE=plume VR_FRAMES=60 VR_WARM=30 VR_DISPLAY=1920x1080 VR_DENOISER=none VR_OUT_DIR="$(cygpath -m $V/$1)" VR_TAG=p \
      timeout 900 $MOG --script "$SC\capture_orbit.py" > $V/$1.log 2>&1 )
}
cap default ""; cap nospec VR_SPECIALIZE=0; cap g8x8 VR_GROUP=8x8; cap nohoist VR_HOIST_ATLAS=0
python - "$V" <<'PY'
import glob, os, sys, hashlib
V = sys.argv[1]; h = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
base = {os.path.basename(f): h(f) for f in glob.glob(V + "/default/*.png")}
for t in ("nospec", "g8x8", "nohoist"):
    fs = {os.path.basename(f): h(f) for f in glob.glob(V + "/" + t + "/*.png")}
    common = set(base) & set(fs)
    print("identity plume %-8s frames %d, byte-identical %d" % (t, len(common), sum(base[k] == fs[k] for k in common)))
PY
echo PLUME REDO DONE
