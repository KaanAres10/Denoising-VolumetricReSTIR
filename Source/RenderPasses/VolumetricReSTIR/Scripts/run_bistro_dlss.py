# Bistro + Volumetric ReSTIR + DLSS (Phase 1: sidecar guide buffers, no pass changes).
#
# DLSSPass requires color, depth AND mvec, and none of them are optional -- an unconnected input is
# a graph compile error. VolumetricReSTIR has no depth output, so this script adds a GBufferRaster
# purely to supply depth + motion vectors, exactly as Falcor's own DLSS graphs do
# (tests/image_tests/renderpasses/graphs/DLSS.py, scripts/PathTracerNRD.py).
#
# WHAT THIS DOES AND DOES NOT GIVE YOU
#
#   + Proves the DLSS pipeline runs end to end, and gives a frame-time baseline.
#   - NO performance win. With outputSize 'Default' the pass treats its input as the render size,
#     upscales internally to ~1.72x (Balanced), then blits back down to the swapchain. You pay
#     full-res ReSTIR *plus* DLSS at a larger target *plus* a downsample -- strictly slower than
#     not using DLSS. The perf win requires the producer to render smaller (Phase 3).
#   - The guides describe OPAQUE GEOMETRY, not the medium. Bistro's surfaces stay crisp while the
#     smoke ghosts, because the GBuffer knows nothing about the plume. Phase 2 replaces these with
#     volume-aware guides produced by VolumetricReSTIR itself.
#
# JITTER: defaults OFF (samplePattern 'Center' -> null generator -> jitter forced to (0,0)), so
# primary rays are bit-identical to every other script and the estimator is untouched. DLSS cannot
# resolve sub-pixel detail without jitter, so expect a softer image than DLSS is capable of.
# Set VR_JITTER=1 to enable Halton and A/B it -- but note that until the prev-jitter fix lands,
# jitter + temporal reuse can bias silhouette pixels (the previous frame's reservoirs were built on
# a jittered ray while p-hat is evaluated on an unjittered one).
#
#   VR_JITTER=0|1     camera jitter (default 0)
#   VR_PROFILE        MaxPerf | Balanced (default) | MaxQuality
#
# Run:  Mogwai.exe --script run_bistro_dlss.py

import os

from falcor import *

DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"
JITTER = os.environ.get("VR_JITTER", "0") not in ("0", "", "false", "False")
PROFILE = os.environ.get("VR_PROFILE", "Balanced")

m.loadScene(DATA_DIR + r"\Bistro_5_1\BistroExterior.fbx")

# Dense smoke plume (fork's original parameters). sigma_s=80 is what gives the plume its density,
# structure and coloured scattering -- thinning it out washes both the detail and the colour away.
m.scene.addGVDBVolume(sigma_a=float3(10, 10, 10), sigma_s=float3(80, 80, 80), g=0.0,
                      dataFile=DATA_DIR + r"\smoke-plume-2", numMips=4)

m.scene.camera.position = float3(-15.149291, 8.352362, -8.399609)
m.scene.camera.target = float3(-14.742913, 8.025879, -7.546224)
m.scene.camera.up = float3(0.004061, 0.999961, 0.007782)


def render_graph():
    g = RenderGraph("Bistro DLSS")

    vr = createPass("VolumetricReSTIR", {'mParams': {
        'mUseSurfaceScene': True,        # shade the Bistro geometry (surface-scene path)
        'mUseEmissiveLights': True,      # the scene's many emissive lights
        'mUseEnvironmentLights': False,  # night scene, no sky contribution
        'mTemporalReuseMThreshold': 10.0,
    }})
    g.addPass(vr, "VolumetricReSTIR")

    # Sidecar producer of depth + mvec. 'Center' installs a null jitter generator, which resets the
    # camera jitter to (0,0); 'Halton' installs the pattern DLSS actually wants.
    gb = createPass("GBufferRaster", {'samplePattern': 'Halton' if JITTER else 'Center',
                                      'sampleCount': 32})
    g.addPass(gb, "GBufferRaster")

    # motionVectorScale MUST be 'Relative': Falcor's motion vectors are normalized [0,1], while the
    # DLSSPass default is 'Absolute' (pixels).
    dlss = createPass("DLSSPass", {'enabled': True, 'profile': PROFILE,
                                   'motionVectorScale': 'Relative', 'isHDR': True,
                                   'sharpness': 0.0, 'exposure': 0.0, 'outputSize': 'Default'})
    g.addPass(dlss, "DLSSPass")

    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 8.0})
    g.addPass(tm, "ToneMapper")

    # DLSS wants linear HDR radiance, pre-tonemap -- hence ToneMapper last.
    g.addEdge("VolumetricReSTIR.accumulated_color", "DLSSPass.color")
    g.addEdge("GBufferRaster.depth", "DLSSPass.depth")
    g.addEdge("GBufferRaster.mvec", "DLSSPass.mvec")
    g.addEdge("DLSSPass.output", "ToneMapper.src")

    g.markOutput("ToneMapper.dst")
    # Marked so the guides can be inspected -- on a pure-volume scene the depth buffer is uniformly
    # far, which is exactly the limitation Phase 2 removes.
    g.markOutput("GBufferRaster.depth")
    g.markOutput("GBufferRaster.mvec")
    return g


print("[dlss] profile=" + PROFILE + " jitter=" + ("Halton" if JITTER else "Center (off)"))

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
