#!/bin/bash
# Precise vs fast math (VR_FP_MODE_VOLUME=fast) through every denoiser, on volume-only scenes.
#  A. Accuracy: plume, static camera (compare_denoisers_plume.py, "V11"), HDR, 200 frames, MSE against a
#     brute-force path-traced reference (3000 accumulated frames, precise). raw / OIDN / OptiX / DLSS RR.
#  B. Temporal stability: plume and bistro volume-only orbits (capture_orbit.py, the matched denoiser
#     settings of the locked table), 120 frames, scored with m_denoisers.py's metric (lower = steadier).
#     raw / OptiX / RELAX-SH / REBLUR-SH / DLSS RR. Frames are deleted once scored (disk).
#   denoisers.sh [A|B|AB]
R=/c/research/Denoising-VolumetricReSTIR; cd $R
O=$R/outputs/pending_9p/fastmath/den; mkdir -p $O
MOG=./build/windows-vs2022/bin/Release/Mogwai.exe
SC='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts'
IC=./build/windows-vs2022/bin/Release/ImageCompare.exe
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
clean_env() { for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset $v; done; }
parts=${1:-AB}

if [[ $parts == *A* ]]; then
  A=$O/v11; mkdir -p $A
  v11() { # tag mode frames fp
    ( clean_env; [ -n "$4" ] && export VR_FP_MODE_VOLUME=$4
      VR_MODE=$2 VR_FRAMES=$3 VR_TAG=$1 VR_EXIT_AFTER_CAPTURE=1 VR_OUT_DIR="$(cygpath -w $A)" timeout 3000 $MOG --script "$SC\compare_denoisers_plume.py" > $A/$1.log 2>&1 )
  }
  [ -n "$(ls $A/ref.*.exr 2>/dev/null)" ] || v11 ref reference 3000 ""
  REF=$(ls $A/ref.*.exr | head -1)
  for mode in none oidn optix rr; do
    for fp in precise fast; do
      v11 ${mode}_$fp $mode 200 $([ $fp = fast ] && echo fast)
      f=$(ls $A/${mode}_$fp.*.exr 2>/dev/null | head -1)
      if [ -z "$f" ]; then echo "A $mode $fp: NO CAPTURE"; continue; fi
      echo "A plume static  $(printf '%-6s %-8s' $mode $fp) MSE $($IC -m mse $REF $f 2>&1 | tail -1)  MAPE $($IC -m mape $REF $f 2>&1 | tail -1)"
    done
  done
fi

if [[ $parts == *B* ]]; then
  B=$O/orbit; mkdir -p $B
  orbit() { # dir scene surface denoiser method fp
    ( clean_env; [ -n "$3" ] && export VR_USE_SURFACE=$3; [ -n "$6" ] && export VR_FP_MODE_VOLUME=$6
      mkdir -p $B/$1
      VR_SCENE=$2 VR_FRAMES=120 VR_WARM=30 VR_DISPLAY=1920x1080 VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient \
        VR_DENOISER=$4 VR_NRD_METHOD=$5 VR_OUT_DIR="$(cygpath -m $B/$1)" VR_TAG=d timeout 1500 $MOG --script "$SC\capture_orbit.py" > $B/$1.log 2>&1 )
  }
  for scene in plume bvol; do
    sc=$scene; surf=""; [ $scene = bvol ] && { sc=bistro; surf=0; }
    for den in "raw none RelaxDiffuseSh" "optix optix RelaxDiffuseSh" "relax nrd RelaxDiffuseSh" "reblur nrd ReblurDiffuseSh" "rr rr RelaxDiffuseSh"; do
      set -- $den
      for fp in precise fast; do
        d=${scene}_$1_$fp
        orbit $d $sc "$surf" $2 $3 $([ $fp = fast ] && echo fast)
        python $R/outputs/pending_9p/fastmath/score.py $B/$d "$scene $1 $fp"
        rm -rf $B/$d
      done
    done
  done
fi
echo DENOISERS DONE
