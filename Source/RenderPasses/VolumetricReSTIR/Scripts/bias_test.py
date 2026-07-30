# Bias test: does ReSTIR converge to the same image as brute-force volumetric path tracing?
#
# An unbiased estimator must converge to the ground truth. mUseReference=True switches the pass to a
# plain volumetric path tracer (temporal/spatial reuse are skipped entirely), so accumulating both
# modes on the same frame and comparing means answers the question directly -- and tests the whole
# chain, rather than the pdf algebra alone.
#
# Bistro is the scene that matters here: the one estimator change the 8.0 port had to make is the
# emissive pdfArea reconstruction (TriangleLightSample::pdfArea was removed in 8.0), and that code
# only runs for emissive lights. An environment-lit scene like the plume would not exercise it.
#
#   VR_MODE=reference   brute-force volumetric path tracing (ground truth)
#   VR_MODE=restir      ReSTIR with temporal + spatial reuse (default)
#   VR_FRAMES=N         accumulation frames before capture (default 512)
#   VR_OUT_DIR=path     where to write the capture
#
# Run both, then compare the two images. Equal means within noise => unbiased. A systematic offset
# in the same direction across the image => bias.
#
# Run:  VR_MODE=reference Mogwai.exe --script bias_test.py
#       VR_MODE=restir    Mogwai.exe --script bias_test.py

import os

from falcor import *

DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"
MODE = os.environ.get("VR_MODE", "restir").lower()
FRAMES = int(os.environ.get("VR_FRAMES", "512"))
OUT_DIR = os.environ.get("VR_OUT_DIR", r"C:\research\Denoising-VolumetricReSTIR\shots\bias")
USE_REFERENCE = MODE == "reference"

m.loadScene(DATA_DIR + r"\Bistro_5_1\BistroExterior.fbx")

m.scene.addGVDBVolume(sigma_a=float3(10, 10, 10), sigma_s=float3(80, 80, 80), g=0.0,
                      dataFile=DATA_DIR + r"\smoke-plume-2", numMips=4)

m.scene.camera.position = float3(-15.149291, 8.352362, -8.399609)
m.scene.camera.target = float3(-14.742913, 8.025879, -7.546224)
m.scene.camera.up = float3(0.004061, 0.999961, 0.007782)


def render_graph():
    g = RenderGraph("Bias test (" + MODE + ")")
    vr = createPass("VolumetricReSTIR", {'mParams': {
        'mUseSurfaceScene': True,
        'mUseEmissiveLights': True,      # exercises the reconstructed emissive pdfArea
        'mUseEnvironmentLights': False,
        'mUseReference': USE_REFERENCE,  # True = brute-force volumetric path tracing
        # Reuse is skipped anyway when mUseReference is set; state it explicitly so the two runs
        # differ in exactly one intended way.
        'mEnableTemporalReuse': not USE_REFERENCE,
        'mEnableSpatialReuse': not USE_REFERENCE,
    }})
    g.addPass(vr, "VolumetricReSTIR")
    acc = createPass("AccumulatePass", {'enabled': True})
    g.addPass(acc, "AccumulatePass")
    # Identical tone mapping in both runs, so any difference is in the radiance, not the mapping.
    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 8.0})
    g.addPass(tm, "ToneMapper")
    g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
    g.addEdge("AccumulatePass.output", "ToneMapper.src")
    g.markOutput("ToneMapper.dst")
    return g


print("[bias] mode=" + MODE + " useReference=" + str(USE_REFERENCE) + " frames=" + str(FRAMES))

m.addGraph(render_graph())
# Lower resolution converges far faster; bias shows up in the mean, which needs far fewer samples
# than a per-pixel-clean image.
m.resizeSwapChain(960, 540)
m.ui = True

os.makedirs(OUT_DIR, exist_ok=True)
m.frameCapture.outputDir = OUT_DIR
m.frameCapture.baseFilename = "bias_" + MODE
m.frameCapture.addFrames(m.activeGraph, [FRAMES])
