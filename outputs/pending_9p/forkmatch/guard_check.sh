#!/bin/bash
# The fork-parity fixes (alpha test in shadow/visibility rays, light-sample offset): compiled out with
# VR_PRE_FORK_PARITY=1 the locked bistro raw orbit must come back byte-identical; left in, how much of it
# changes, and (if orbit/fixed_ref holds an earlier capture of the fixed code) that nothing else did.
#   guard_check.sh
R=/c/research/Denoising-VolumetricReSTIR; cd $R
O=$R/outputs/pending_9p/forkmatch/orbit; mkdir -p $O
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
cap() { # tag slang-args
  ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
    [ -n "$2" ] && export VR_SLANG_ARGS="$2"
    rm -rf $O/$1; mkdir -p $O/$1
    VR_SCENE=bistro VR_FRAMES=300 VR_WARM=30 VR_DISPLAY=1920x1080 VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient VR_DENOISER=none VR_NRD_METHOD=RelaxDiffuseSh VR_OUT_DIR="$(cygpath -m $O/$1)" VR_TAG=rb \
      timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\capture_orbit.py" > $O/$1.log 2>&1 )
}
cap nofix "-DVR_PRE_FORK_PARITY=1"
cap fixed ""
python - $R/outputs/rb_v9p_raw $O <<'PY'
import glob, hashlib, os, sys
import numpy as np, cv2
L, O = sys.argv[1:]
h = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
for tag in ("nofix", "fixed"):
    names = sorted(set(map(os.path.basename, glob.glob(L + "/*.png"))) & set(map(os.path.basename, glob.glob(O + "/" + tag + "/*.png"))))
    same = sum(h(L + "/" + n) == h(O + "/" + tag + "/" + n) for n in names)
    mu = lambda d: np.mean([cv2.imread(d + "/" + n)[..., :3].mean() for n in names[::10]])
    print("%-6s vs locked raw: frames %d, byte-identical %d   mean %.3f vs locked %.3f" % (tag, len(names), same, mu(O + "/" + tag), mu(L)))
if os.path.isdir(O + "/fixed_ref"):
    names = sorted(set(map(os.path.basename, glob.glob(O + "/fixed_ref/*.png"))) & set(map(os.path.basename, glob.glob(O + "/fixed/*.png"))))
    print("fixed  vs fixed_ref: frames %d, byte-identical %d" % (len(names), sum(h(O + "/fixed_ref/" + n) == h(O + "/fixed/" + n) for n in names)))
PY
echo GUARD DONE
