# Volumetric ReSTIR + DLSS with VOLUME-AWARE guide buffers (Phase 2).
#
# Unlike run_bistro_dlss.py, there is no GBuffer here. VolumetricReSTIR produces the depth and
# motion vectors itself, so they describe the participating medium rather than opaque geometry --
# which is the only thing that works on a pure-volume scene like the plume, where a GBuffer would
# report "everything is at the far plane".
#
#   linearZ  transmittance-weighted mean scattering distance E[t], converted to linear view Z.
#            Deterministic (consumes no random numbers), so it is temporally stable -- unlike
#            Reservoir::depth, which is a stochastic free-flight sample and flickers every frame.
#   mvec     computed from that same expected scatter point, advected backwards through the
#            velocity grid so the plume's own motion is represented, then projected with the
#            previous frame's view-projection. Sub-pixel and written every frame.
#
# Verified motion-vector conventions (camera pans -> sign of the vector, current->previous):
#   static  -> exactly zero      pan right -> mvec.x positive      pan down -> mvec.y positive
#
#   VR_ANIMATED=1     play the 16-frame fire115 sequence instead of the static frame
#   VR_PROFILE        MaxPerf | Balanced (default) | MaxQuality
#   VR_DEPTH_NDC=1    feed NDC depth instead of linear view Z (A/B which DLSS prefers)
#
# NOTE: still no performance win -- that needs render scale (Phase 3). This script exists to prove
# the volume-aware guides work; see run_plume_dlss_upscale.py for the configuration that is
# actually faster.
#
# Run:  Mogwai.exe --script run_plume_dlss.py

import os

from falcor import *

DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"
ANIMATED = os.environ.get("VR_ANIMATED", "0") not in ("0", "", "false", "False")
PROFILE = os.environ.get("VR_PROFILE", "Balanced")
DEPTH_NDC = os.environ.get("VR_DEPTH_NDC", "0") not in ("0", "", "false", "False")

STATIC_FRAME = "fire115.0198"
START_FRAME = 100
NUM_FRAMES = 16

m.loadScene(DATA_DIR + r"\default.obj")
m.scene.setEnvMap(DATA_DIR + r"\hansaplatz_8k.hdr")

COMMON = dict(
    sigma_a=float3(6, 6, 6), sigma_s=float3(14, 14, 14), g=0.0,
    numMips=4, densityScale=0.1, hasEmission=False, LeScale=0.01,
    temperatureCutoff=900.0, temperatureScale=0.0,
    worldTranslation=float3(0, 1.686, 0), worldRotation=float3(0, 0, 0), worldScaling=0.013)

if ANIMATED:
    m.scene.addGVDBVolumeSequence(
        dataFilePrefix=DATA_DIR + r"\fire115\fire115.", numberFixedLength=4,
        startFrame=START_FRAME, numFrames=NUM_FRAMES, hasVelocity=True, **COMMON)
else:
    m.scene.addGVDBVolume(
        dataFile=DATA_DIR + "\\fire115\\" + STATIC_FRAME, hasVelocity=False, **COMMON)

m.scene.cameraSpeed = 1
m.scene.camera.position = float3(1.977354, 2.411630, 2.242076)
m.scene.camera.target = float3(1.366226, 2.220231, 1.474033)
m.scene.camera.up = float3(0.0, 1.0, 0.0)


def render_graph():
    g = RenderGraph("Plume DLSS")

    vr = createPass("VolumetricReSTIR", {
        'mOutputDepth': True,
        'mDepthAsNDC': DEPTH_NDC,
        'mMotionVecMode': 'Deterministic',
        'mParams': {
            'mEnableTemporalReuse': True,
            'mEnableSpatialReuse': True,
            'mUseEnvironmentLights': True,
            'mUseEmissiveLights': False,
        }})
    g.addPass(vr, "VolumetricReSTIR")

    # motionVectorScale MUST be 'Relative': our mvec is normalized [0,1], the pass default is pixels.
    dlss = createPass("DLSSPass", {'enabled': True, 'profile': PROFILE,
                                   'motionVectorScale': 'Relative', 'isHDR': True,
                                   'sharpness': 0.0, 'exposure': 0.0, 'outputSize': 'Default'})
    g.addPass(dlss, "DLSSPass")

    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 0.0})
    g.addPass(tm, "ToneMapper")

    # DLSS wants linear HDR radiance, pre-tonemap.
    g.addEdge("VolumetricReSTIR.accumulated_color", "DLSSPass.color")
    g.addEdge("VolumetricReSTIR.linearZ", "DLSSPass.depth")
    g.addEdge("VolumetricReSTIR.mvec", "DLSSPass.mvec")
    g.addEdge("DLSSPass.output", "ToneMapper.src")

    g.markOutput("ToneMapper.dst")
    return g


print("[dlss] plume=" + ("animated" if ANIMATED else "static " + STATIC_FRAME)
      + " profile=" + PROFILE + " depth=" + ("NDC" if DEPTH_NDC else "linearZ"))

m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True

# Optional capture: VR_CAPTURE_FRAME=N writes the DLSS result to shots/dlss_gallery/ at frame N.
_cap = int(os.environ.get("VR_CAPTURE_FRAME", "0"))
if _cap > 0:
    _out = os.environ.get("VR_OUT_DIR", r"C:\research\Denoising-VolumetricReSTIR\shots\dlss_gallery")
    os.makedirs(_out, exist_ok=True)
    m.frameCapture.outputDir = _out
    m.frameCapture.baseFilename = os.environ.get("VR_TAG", "shot")
    m.frameCapture.addFrames(m.activeGraph, [_cap])
