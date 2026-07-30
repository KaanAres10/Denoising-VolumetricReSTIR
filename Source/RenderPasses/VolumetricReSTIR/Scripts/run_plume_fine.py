# The fire115 plume with fine-grained volume sampling, to see the square/brick artifacts with the
# coarse-mip and point-sampling defaults turned off.
#
#     param                                default   fine    effect
#     mInitialBaseMipLevel                 1         0       primary visibility at full resolution
#     mInitialLightingMipLevel             2         0       lighting at full resolution
#     mInitialVisibilityUseLinearSampler   False     True    trilinear instead of nearest -> no hard
#                                                            square edges (the default already uses
#                                                            linear for *lighting*, not visibility)
#     mTemporalReprojectionMipLevel        1         0
#     mSpatialVisibilityMipLevel           1         0
#     mSpatialLightingMipLevel             1         0
#
# Env switches:
#     VR_FINE=0       run with the stock coarse defaults, for a direct A/B on the same camera
#     VR_ANIMATED=1   play the 16-frame sequence instead of freezing one frame
#
# Defaults to the STATIC frame: nothing moves, so AccumulatePass converges and you are judging the
# sampling rather than temporal noise. Switch to animated once you know what the artifact looks like.
#
# Run:  Mogwai.exe --script run_plume_fine.py
#       (or VS Code -> Run Task -> "Run: plume (fine sampling)")

import os

from falcor import *

DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"
FINE = os.environ.get("VR_FINE", "1") not in ("0", "", "false", "False")
ANIMATED = os.environ.get("VR_ANIMATED", "0") not in ("0", "", "false", "False")

# Static frame to freeze on, and the animated range. Both must be pre-baked (see Source/Tools/GVDBBake)
# with flags matching the load below -- baked frames are 0100..0115 (with velocity) and 0198 (without).
STATIC_FRAME = "fire115.0198"
START_FRAME = 100
NUM_FRAMES = 16

m.loadScene(DATA_DIR + r"\default.obj")
m.scene.setEnvMap(DATA_DIR + r"\hansaplatz_8k.hdr")

# Fork's original plume parameters, shared by both paths.
COMMON = dict(
    sigma_a=float3(6, 6, 6), sigma_s=float3(14, 14, 14), g=0.0,
    numMips=4, densityScale=0.1, hasEmission=False, LeScale=0.01,
    temperatureCutoff=900.0, temperatureScale=0.0,
    worldTranslation=float3(0, 1.686, 0), worldRotation=float3(0, 0, 0), worldScaling=0.013)

if ANIMATED:
    # hasVelocity=True: the sequence was baked with velocity for temporal reprojection.
    m.scene.addGVDBVolumeSequence(
        dataFilePrefix=DATA_DIR + r"\fire115\fire115.", numberFixedLength=4,
        startFrame=START_FRAME, numFrames=NUM_FRAMES, hasVelocity=True, **COMMON)
else:
    # hasVelocity=False: a frozen frame has no previous frame to reproject from, and 0198 was baked
    # without velocity -- the load flags must match the bake flags.
    m.scene.addGVDBVolume(
        dataFile=DATA_DIR + "\\fire115\\" + STATIC_FRAME, hasVelocity=False, **COMMON)

m.scene.cameraSpeed = 1
m.scene.camera.position = float3(1.977354, 2.411630, 2.242076)
m.scene.camera.target = float3(1.366226, 2.220231, 1.474033)
m.scene.camera.up = float3(0.0, 1.0, 0.0)


def volume_params():
    p = {
        'mEnableTemporalReuse': True,
        'mEnableSpatialReuse': True,
        'mUseEnvironmentLights': True,
        'mUseEmissiveLights': False,
    }
    if FINE:
        p.update({
            'mInitialBaseMipLevel': 0,
            'mInitialLightingMipLevel': 0,
            'mInitialVisibilityUseLinearSampler': True,
            'mInitialLightingUseLinearSampler': True,
            'mTemporalReprojectionMipLevel': 0,
            'mSpatialVisibilityMipLevel': 0,
            'mSpatialLightingMipLevel': 0,
        })
    return p


def render_graph():
    g = RenderGraph("Plume" + (" (fine)" if FINE else " (default)") + (" animated" if ANIMATED else " static"))
    vr = createPass("VolumetricReSTIR", {'mOutputMotionVec': True, 'mParams': volume_params()})
    g.addPass(vr, "VolumetricReSTIR")
    # Accumulation converges only while the volume is still; it resets every frame when animated.
    acc = createPass("AccumulatePass", {'enabled': not ANIMATED})
    g.addPass(acc, "AccumulatePass")
    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 0.0})
    g.addPass(tm, "ToneMapper")
    g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
    g.addEdge("AccumulatePass.output", "ToneMapper.src")
    g.markOutput("ToneMapper.dst")
    g.markOutput("VolumetricReSTIR.mvec")  # temporal reuse binds the motion-vector output
    return g


print("[fine] plume: " + ("ANIMATED" if ANIMATED else "STATIC " + STATIC_FRAME)
      + ", sampling: " + ("FINE (mip 0, linear)" if FINE else "DEFAULTS"))

m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True
