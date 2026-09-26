#!/bin/bash
# Where does the fork's sparser image come from? The verify frame (bistro, orbit pose 150, raw estimator,
# +8 EV Linear) from the fork and from 9.0 with temporal / spatial reuse switched off stage by stage
# (VR_NO_TEMPORAL / VR_NO_SPATIAL in both scripts). Black-pixel share per region, mean.   stages.sh
R=/c/research/Denoising-VolumetricReSTIR; cd $R
O=$R/outputs/pending_9p/forkmatch/stages; mkdir -p $O
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
one() { # engine tag env...
  local eng=$1 tag=$2; shift 2
  ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
    for kv in "$@"; do export "$kv"; done
    rm -rf $O/${eng}_$tag; mkdir -p $O/${eng}_$tag
    if [ $eng = fork ]; then
      cd $R/legacy; VR_VERIFY=1 VR_OUT_DIR="$(cygpath -w $O/${eng}_$tag)" timeout 600 ./Bin/x64/Release/Mogwai.exe --script "$(cygpath -w $R/legacy/Scripts/_time_raw_legacy.py)" > $O/${eng}_$tag.log 2>&1
    else
      VR_VERIFY=1 VR_ENGINE=v9 VR_OUT_DIR="$(cygpath -m $O/${eng}_$tag)" timeout 600 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py" > $O/${eng}_$tag.log 2>&1
    fi )
}
for st in "reuse" "notemporal VR_NO_TEMPORAL=1" "nospatial VR_NO_SPATIAL=1" "noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1"; do
  set -- $st; tag=$1; shift
  one fork $tag "$@"; one v9 $tag "$@"
done
python - $O <<'PY'
import glob, sys, cv2, numpy as np
O = sys.argv[1]
reg = {"plume core": np.s_[250:700, 900:1150], "street": np.s_[800:1080, 0:700], "facade": np.s_[0:300, 0:700], "cafe": np.s_[300:800, 1550:1920], "whole": np.s_[:, :]}
print("%-16s" % "black %" + "".join("%11s" % r for r in reg) + "   mean")
for tag in ("reuse", "notemporal", "nospatial", "noreuse"):
    for eng in ("fork", "v9"):
        f = glob.glob("%s/%s_%s/*.png" % (O, eng, tag))
        if not f: print("%-16s (no frame)" % (eng + " " + tag)); continue
        x = cv2.imread(f[0])[..., :3]
        print("%-16s" % (eng + " " + tag) + "".join("%11.1f" % (100 * (x[s].max(-1) == 0).mean()) for s in reg.values()) + "   %.2f" % x.mean())
PY
echo STAGES DONE
