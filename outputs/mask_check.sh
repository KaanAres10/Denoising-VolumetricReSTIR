#!/bin/bash
# Byte-identity check: capture <cfg> (raw|relax|...) with the matched settings, compare with rb_v9p_<cfg>.
cfg="$1"; den="$2"; meth="${3:-RelaxDiffuseSh}"
cd /c/research/Denoising-VolumetricReSTIR
for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done
# The rb_v9p captures predate the fork-parity fixes (alpha-tested shadow rays, offset light samples) and the
# GVDB DDA clamp (axis-parallel rays): compile them out so an unrelated change can still be checked for
# byte-identity against them.
export VR_SLANG_ARGS="-DVR_PRE_FORK_PARITY=1 -DVR_PRE_DDA_CLAMP=1"
rm -rf outputs/mask_check_$cfg; mkdir -p outputs/mask_check_$cfg
ls build/windows-vs2022/bin/Release/libprotoc.dll build/windows-vs2022/bin/Release/z.dll >/dev/null 2>&1 || ./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target restore_runtime_dlls >/dev/null 2>&1
VR_SCENE=bistro VR_FRAMES=300 VR_WARM=30 VR_DISPLAY=1920x1080 VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient VR_DENOISER=$den VR_NRD_METHOD=$meth VR_OUT_DIR="C:/research/Denoising-VolumetricReSTIR/outputs/mask_check_$cfg" VR_TAG=rb timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe --script "C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\capture_orbit.py" > outputs/mask_check_$cfg/run.log 2>&1
cd outputs && python - "$cfg" <<'PY'
import hashlib, glob, os, sys
cfg = sys.argv[1]
a = "rb_v9p_" + cfg; b = "mask_check_" + cfg
names = sorted(set(map(os.path.basename, glob.glob(a + "/*.png"))) & set(map(os.path.basename, glob.glob(b + "/*.png"))))
h = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
same = sum(1 for n in names if h(a + "/" + n) == h(b + "/" + n))
print("%s: frames compared %d, byte-identical %d, stall %s" % (cfg, len(names), same, os.path.exists(b + "/CLOCK_STALL.txt")))
PY
