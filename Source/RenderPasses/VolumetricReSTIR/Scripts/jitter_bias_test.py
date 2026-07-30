# Does camera jitter bias the estimator, and does the gPrevJitter fix remove it?
#
# Jitter is required for DLSS to resolve subpixel detail, but temporal reuse re-evaluates the
# PREVIOUS frame's reservoirs. Those were generated on a jittered ray; if p-hat is evaluated on an
# unjittered one, p-hat is wrong for that domain. Talbot MIS weights renormalise, so the usual cost
# is variance -- except where the wrong ray flips a hit to a miss (silhouettes), where p-hat is
# exactly zero, the weights stop summing to one, and the result is genuinely BIASED.
#
# THE COMPARISON THAT ISOLATES IT. Comparing jitter-on against jitter-off does NOT work: jitter also
# performs pixel-area antialiasing, so the two converge to legitimately different images at edges --
# exactly where the bias lives. Instead compare the two JITTERED configurations against each other.
# They share the same Halton sequence and therefore the same sample positions; the only difference is
# whether p-hat uses the correct previous-frame ray. Any systematic difference is the bias.
#
#   VR_CFG=fix     jitter on, gPrevJitter applied (correct)
#   VR_CFG=nofix   jitter on, gPrevJitter forced to 0 (pre-fix behaviour)
#   VR_CFG=off     jitter off (context; not directly comparable to the above, see note)
#
# Bistro, not the plume: this needs hard geometric silhouettes, which a soft volume does not have.
# Captures HDR (AccumulatePass.output -> .exr), never a tone-mapped PNG -- clamping fireflies would
# discard energy in proportion to variance and manufacture a fake difference.

import os

from falcor import *

DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"
CFG = os.environ.get("VR_CFG", "fix").lower()
FRAMES = int(os.environ.get("VR_FRAMES", "2048"))
OUT_DIR = os.environ.get("VR_OUT_DIR", r"C:\research\Denoising-VolumetricReSTIR\shots\jitter")

JITTER = CFG in ("fix", "nofix")
APPLY_PREV_JITTER = CFG != "nofix"

m.loadScene(DATA_DIR + r"\Bistro_5_1\BistroExterior.fbx")

m.scene.addGVDBVolume(sigma_a=float3(10, 10, 10), sigma_s=float3(80, 80, 80), g=0.0,
                      dataFile=DATA_DIR + r"\smoke-plume-2", numMips=4)

m.scene.camera.position = float3(-15.149291, 8.352362, -8.399609)
m.scene.camera.target = float3(-14.742913, 8.025879, -7.546224)
m.scene.camera.up = float3(0.004061, 0.999961, 0.007782)


def render_graph():
    g = RenderGraph("Jitter bias (" + CFG + ")")
    vr = createPass("VolumetricReSTIR", {
        'samplePattern': 'Halton' if JITTER else 'Center',
        'sampleCount': 32,
        'mApplyPrevJitter': APPLY_PREV_JITTER,
        'mParams': {
            'mUseSurfaceScene': True,      # hard silhouettes are the point
            'mUseEmissiveLights': True,
            'mUseEnvironmentLights': False,
            'mEnableTemporalReuse': os.environ.get('VR_TEMPORAL','1') not in ('0',''),
            'mEnableSpatialReuse': True,
            'mTemporalReuseMThreshold': 10.0,
        }})
    g.addPass(vr, "VolumetricReSTIR")
    acc = createPass("AccumulatePass", {'enabled': os.environ.get('VR_ACCUM','1') not in ('0','')})
    g.addPass(acc, "AccumulatePass")
    g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
    g.markOutput("AccumulatePass.output")   # HDR, not tone mapped
    return g


print("[jitter] cfg=" + CFG + " jitter=" + str(JITTER) + " applyPrevJitter=" + str(APPLY_PREV_JITTER))

m.addGraph(render_graph())
m.resizeSwapChain(960, 540)
m.ui = True

os.makedirs(OUT_DIR, exist_ok=True)
m.frameCapture.outputDir = OUT_DIR
m.frameCapture.baseFilename = "jit_" + CFG
m.frameCapture.addFrames(m.activeGraph, [FRAMES])
