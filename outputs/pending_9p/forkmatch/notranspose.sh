#!/bin/bash
# The verify frame with the previous-frame matrices NOT transposed (time_raw_notranspose.py), next to
# stages.sh's: is a wrong reprojection what makes the fork's temporal reuse sparse?   notranspose.sh
R=/c/research/Denoising-VolumetricReSTIR; cd $R
O=$R/outputs/pending_9p/forkmatch/stages
SP="C:/research/Denoising-VolumetricReSTIR/outputs/pending_9p/forkmatch"
for st in "reuse" "nospatial VR_NO_SPATIAL=1"; do
  set -- $st; tag=$1; shift
  ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
    for kv in "$@"; do export "$kv"; done
    rm -rf $O/v9nt_$tag; mkdir -p $O/v9nt_$tag
    VR_VERIFY=1 VR_ENGINE=v9 VR_OUT_DIR="$(cygpath -m $O/v9nt_$tag)" timeout 600 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "$SP/time_raw_notranspose.py" > $O/v9nt_$tag.log 2>&1 )
done
python - $O <<'PY'
import glob, sys, cv2, numpy as np
O = sys.argv[1]
reg = {"plume core": np.s_[250:700, 900:1150], "street": np.s_[800:1080, 0:700], "facade": np.s_[0:300, 0:700], "cafe": np.s_[300:800, 1550:1920], "whole": np.s_[:, :]}
for tag in ("reuse", "nospatial"):
    for eng in ("fork", "v9", "v9nt"):
        f = glob.glob("%s/%s_%s/*.png" % (O, eng, tag))
        if not f: print("%-16s (no frame)" % (eng + " " + tag)); continue
        x = cv2.imread(f[0])[..., :3]
        print("%-16s" % (eng + " " + tag) + "".join("%11.1f" % (100 * (x[s].max(-1) == 0).mean()) for s in reg.values()) + "   %.2f" % x.mean())
PY
echo NT DONE
