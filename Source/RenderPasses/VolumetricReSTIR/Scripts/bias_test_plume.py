# Cheap bias test: does ReSTIR converge to the same image as brute-force volumetric path tracing?
#
# Static plume lit by exactly ONE point light. Chosen so the reference path tracer converges in
# minutes -- with a single easy-to-sample light there are no rare high-energy paths, so variance is
# low enough that a few thousand samples is a genuine ground truth. (The Bistro variant exercises
# the reconstructed emissive pdfArea, but its ~20k emitters make a real reference an overnight run.)
#
# CAPTURES HDR, NOT TONE-MAPPED. This matters: comparing 8-bit PNGs clamps fireflies at 255, which
# discards energy in proportion to variance and so systematically darkens the noisier image -- it
# manufactures apparent "bias" in whichever estimator is noisier. AccumulatePass.output is
# RGBA32Float and is written as .exr, preserving the full range.
#
#   VR_MODE=reference   brute-force volumetric path tracing (ground truth)
#   VR_MODE=restir      ReSTIR with temporal + spatial reuse
#   VR_FRAMES=N         accumulation frames before capture (default 4096)
#
# Compare with Falcor's own tool, which reads float formats:
#   ImageCompare.exe shots/bias_plume/plume_reference.AccumulatePass.output.<N>.exr \
#                    shots/bias_plume/plume_restir.AccumulatePass.output.<N>.exr -m MSE
#
# Run:  VR_MODE=reference Mogwai.exe --script bias_test_plume.py
#       VR_MODE=restir    Mogwai.exe --script bias_test_plume.py

import os

from falcor import *

DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"
MODE = os.environ.get("VR_MODE", "restir").lower()
FRAMES = int(os.environ.get("VR_FRAMES", "4096"))
OUT_DIR = os.environ.get("VR_OUT_DIR", r"C:\research\Denoising-VolumetricReSTIR\shots\bias_plume")
USE_REFERENCE = MODE == "reference"

# The one point light lives in the .pyscene; analytic lights cannot be added at runtime.
m.loadScene(DATA_DIR + r"\plume_onelight.pyscene")

# Static plume frame, same parameters as run_plume_static.py. hasVelocity=False must match the bake.
m.scene.addGVDBVolume(
    sigma_a=float3(6, 6, 6), sigma_s=float3(14, 14, 14), g=0.0,
    dataFile=DATA_DIR + "\\fire115\\fire115.0198",
    numMips=4, densityScale=0.1, hasVelocity=False, hasEmission=False, LeScale=0.01,
    temperatureCutoff=900.0, temperatureScale=0.0,
    worldTranslation=float3(0, 1.686, 0), worldRotation=float3(0, 0, 0), worldScaling=0.013)


def render_graph():
    g = RenderGraph("Bias plume (" + MODE + ")")
    vr = createPass("VolumetricReSTIR", {
        # Phase 2 guide buffers ON, to prove they do not perturb the estimator. These are pass-level
        # properties, siblings of mParams -- not members of it.
        # Jitter controls, for testing whether jitter (and the gPrevJitter fix) biases the
        # estimator: compare each against the brute-force reference, which is always unjittered.
        'samplePattern': 'Halton' if os.environ.get('VR_JITTER','0') not in ('0','') else 'Center',
        'sampleCount': 32,
        'mApplyPrevJitter': os.environ.get('VR_PREVJIT','1') not in ('0',''),
        'mOutputDepth': True,
        'mMotionVecMode': 'Deterministic',
        'mParams': {
            'mUseAnalyticLights': True,       # the single point light
            'mUseEnvironmentLights': False,
            'mUseEmissiveLights': False,
            'mUseReference': USE_REFERENCE,   # True = brute-force volumetric path tracing
            'mEnableTemporalReuse': not USE_REFERENCE,
            'mEnableSpatialReuse': not USE_REFERENCE,
        }})
    g.addPass(vr, "VolumetricReSTIR")
    acc = createPass("AccumulatePass", {'enabled': True})
    g.addPass(acc, "AccumulatePass")
    # Mark the HDR accumulation output, NOT a tone mapper -- see the note above about clamping.
    g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
    g.markOutput("AccumulatePass.output")
    # Optional outputs are not allocated unless connected or marked; mark them so the guide-buffer
    # code path actually executes during the regression.
    g.markOutput("VolumetricReSTIR.linearZ")
    g.markOutput("VolumetricReSTIR.mvec")
    return g


print("[bias] mode=" + MODE + " useReference=" + str(USE_REFERENCE) + " frames=" + str(FRAMES))

m.addGraph(render_graph())
m.resizeSwapChain(960, 540)
m.ui = True

os.makedirs(OUT_DIR, exist_ok=True)
m.frameCapture.outputDir = OUT_DIR
m.frameCapture.baseFilename = "plume_" + MODE + os.environ.get("VR_TAG","")
m.frameCapture.addFrames(m.activeGraph, [FRAMES])
# VR_EXIT=1: quit once the capture has flushed (it writes asynchronously), for unattended runs.
if os.environ.get("VR_EXIT", "0") not in ("0", ""):
    m.clock.exitFrame = FRAMES + 60
