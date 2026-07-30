# Volumetric ReSTIR rendered BELOW display resolution, upscaled by DLSS (Phase 3).
#
# This is the configuration the research question needs: ReSTIR runs on ~1/3 of the pixels, DLSS
# restores the display resolution, and the freed compute can be reinvested in sampling (more
# mInitialM, more spatial reuse rounds, finer mip levels). Every other DLSS script here renders at
# full resolution and is therefore strictly SLOWER than not using DLSS at all.
#
# HOW THE SIZES WORK. DLSSPass derives its output from its INPUT:
#     mDLSSOutputSize = inputSize^2 / optimalRenderSize
# where optimalRenderSize ~= ratio * inputSize for a per-profile ratio. So feeding it the profile's
# optimal render size for a 1920x1080 target gets ~1920x1080 back. We therefore compute the render
# size from the profile rather than hard-coding it, and leave DLSSPass at outputSize 'Default'
# (swapchain-sized) -- the internal blit is then ~1:1 and effectively free, and we avoid the
# one-frame graph recompile that outputSize 'Fixed' forces.
#
# ASPECT RATIO: the camera aspect comes from the swapchain, not from this pass, so the render size
# must keep the display aspect or the image stretches. The pass logs a warning if it does not.
#
# JITTER: DLSS cannot resolve subpixel detail without a varying subpixel offset, so this script
# turns Halton on. VolumetricReSTIR owns the jitter here (scaled by 1/renderDim, which a GBuffer
# would get wrong) -- there is deliberately no GBuffer in this graph.
#   *** Jitter + temporal reuse is the one setting in this pass that is NOT estimator-neutral: the
#   *** previous frame's reservoirs were built on a jittered ray while p-hat is re-evaluated on an
#   *** unjittered one, which can bias silhouette pixels. Set VR_JITTER=0 to disable and compare.
#
#   VR_PROFILE     MaxPerf | Balanced (default) | MaxQuality
#   VR_JITTER=0|1  camera jitter (default 1)
#   VR_ANIMATED=1  play the 16-frame fire115 sequence
#
# Run:  Mogwai.exe --script run_plume_dlss_upscale.py

import os

from falcor import *

DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"
PROFILE = os.environ.get("VR_PROFILE", "Balanced")
JITTER = os.environ.get("VR_JITTER", "1") not in ("0", "", "false", "False")
ANIMATED = os.environ.get("VR_ANIMATED", "0") not in ("0", "", "false", "False")

DISPLAY = (1920, 1080)
# Nominal DLSS render-scale ratios per profile. These come from the driver at runtime
# (queryOptimalSettings) and are not contractual -- DLSSPass' UI reports the sizes it actually
# chose, so check them on the first run and adjust if they differ.
RATIO = {"MaxPerf": 0.5, "Balanced": 0.58, "MaxQuality": 2.0 / 3.0}.get(PROFILE, 0.58)
# VR_SCALE overrides the profile ratio. Set it to 1.0 to render at full display resolution with an
# otherwise identical graph -- that is the control for measuring what the render scale actually buys.
RATIO = float(os.environ.get("VR_SCALE", RATIO))
# Keep the display aspect ratio; round to even to avoid odd-sized dispatch edges.
RENDER = (int(DISPLAY[0] * RATIO) // 2 * 2, int(DISPLAY[1] * RATIO) // 2 * 2)

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
    g = RenderGraph("Plume DLSS upscale")

    vr = createPass("VolumetricReSTIR", {
        # Render below display resolution. This is the entire source of the performance win.
        'outputSize': 'Fixed',
        'fixedOutputSize': RENDER,
        # This pass owns the jitter, scaled by 1/renderDim.
        'samplePattern': 'Halton' if JITTER else 'Center',
        'sampleCount': 32,
        'mOutputDepth': True,
        'mDepthAsNDC': os.environ.get('VR_DEPTH_NDC','0') not in ('0',''),
        'mMotionVecMode': 'Deterministic',
        'mParams': {
            'mEnableTemporalReuse': True,
            'mEnableSpatialReuse': True,
            'mUseEnvironmentLights': True,
            'mUseEmissiveLights': False,
        }})
    g.addPass(vr, "VolumetricReSTIR")

    dlss = createPass("DLSSPass", {'enabled': True, 'profile': PROFILE,
                                   'motionVectorScale': 'Relative', 'isHDR': True,
                                   'sharpness': 0.0, 'exposure': 0.0, 'outputSize': 'Default'})
    g.addPass(dlss, "DLSSPass")

    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 0.0})
    g.addPass(tm, "ToneMapper")

    g.addEdge("VolumetricReSTIR.accumulated_color", "DLSSPass.color")
    g.addEdge("VolumetricReSTIR.linearZ", "DLSSPass.depth")
    g.addEdge("VolumetricReSTIR.mvec", "DLSSPass.mvec")
    g.addEdge("DLSSPass.output", "ToneMapper.src")

    g.markOutput("ToneMapper.dst")
    return g


px = RENDER[0] * RENDER[1] / float(DISPLAY[0] * DISPLAY[1])
print("[dlss] profile=" + PROFILE + " render=" + str(RENDER[0]) + "x" + str(RENDER[1])
      + " display=" + str(DISPLAY[0]) + "x" + str(DISPLAY[1])
      + " -> {:.0f}% of the pixels".format(100 * px)
      + " jitter=" + ("Halton" if JITTER else "off"))

m.addGraph(render_graph())
m.resizeSwapChain(DISPLAY[0], DISPLAY[1])
m.ui = True

# Optional capture, for the fixed-compute-budget sweep: VR_CAPTURE_FRAME=N writes the upscaled
# result to shots/dlss/ at frame N. The captured image is at DISPLAY resolution regardless of the
# render size, which is what makes render-scale settings directly comparable.
_cap = int(os.environ.get("VR_CAPTURE_FRAME", "0"))
if _cap > 0:
    out = os.environ.get("VR_OUT_DIR", r"C:\research\Denoising-VolumetricReSTIR\shots\dlss")
    os.makedirs(out, exist_ok=True)
    m.frameCapture.outputDir = out
    m.frameCapture.baseFilename = "dlss_" + ("ndc" if os.environ.get("VR_DEPTH_NDC","0") not in ("0","") else "linz")
    m.frameCapture.addFrames(m.activeGraph, [_cap])
