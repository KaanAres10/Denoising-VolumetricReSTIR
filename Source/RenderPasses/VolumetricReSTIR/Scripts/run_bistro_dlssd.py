# Bistro + Volumetric ReSTIR + DLSS Ray Reconstruction (Stage 1: surface guides).
#
# RR is a genuine neural denoiser that ALSO upscales, so unlike DLSS Super Resolution it replaces
# OIDN/OptiX rather than sitting after one. This script is the RR column of the denoiser comparison.
#
# GUIDES: from GBufferRaster, so they describe the Bistro geometry, not the smoke. That is the
# Stage 1 limitation and the reason to start here -- albedo/normal/roughness are unambiguous for
# surfaces, so a bad result means the plumbing is wrong rather than the guides being ill-defined.
# Stage 2 blends in volumetric guides.
#
# DEFAULTS TO DLAA (native resolution, no upscaling). Measure RR as a denoiser first; adding
# upscaling at the same time would confound the two.
#
#   VR_PROFILE=DLAA     DLAA (default) | MaxQuality | Balanced | MaxPerf
#   VR_PRESET=E         RR network: E (latest transformer, default) | D (default transformer)
#   VR_RENDER=WxH       explicit render size; ignored when profile is DLAA
#   VR_DISPLAY=1920x1080
#
# Jitter is REQUIRED for RR and is owned by GBufferRaster here (samplePattern Halton). Note that
# VolumetricReSTIR's camera rays read cam.data.jitterX/Y directly, so they are jittered too --
# setPatternGenerator is global, and whoever installs it affects every pass reading the camera.
#
# Run:  Mogwai.exe --script run_bistro_dlssd.py

import os

from falcor import *

DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"


def _size(name, default):
    v = os.environ.get(name, "")
    if "x" in v.lower():
        try:
            w, h = v.lower().split("x")
            return (int(w), int(h))
        except ValueError:
            pass
    return default


# Stage 2: blend the surface guides toward medium-like values wherever the smoke covers the pixel.
# VR_VOLGUIDES=0 reverts to the Stage 1 surface-only guides (and must be bit-identical to it).
VOLGUIDES = os.environ.get("VR_VOLGUIDES", "1") not in ("0", "", "false", "False")
PROFILE = os.environ.get("VR_PROFILE", "DLAA")
PRESET = os.environ.get("VR_PRESET", "E")
# The pass names presets descriptively now; a plain letter still works. Both live RR models
# are transformer-based -- the CNN networks are exactly the presets NVIDIA removed.
PRESET = {"Default": "Default", "D": "D_Transformer",
          "E": "E_TransformerLatest"}.get(PRESET, PRESET)
DISPLAY = _size("VR_DISPLAY", (1920, 1080))

# DLAA is native resolution: render == display, no upscaling.
if PROFILE == "DLAA":
    RENDER = DISPLAY
else:
    RATIO = {"MaxPerf": 0.5, "Balanced": 0.58, "MaxQuality": 2.0 / 3.0}.get(PROFILE, 0.58)
    RENDER = (int(DISPLAY[0] * RATIO) // 2 * 2, int(DISPLAY[1] * RATIO) // 2 * 2)
RENDER = _size("VR_RENDER", RENDER)

# DLAA renders natively; every other profile upscales by its ratio.
UPSCALE = PROFILE != "DLAA"
RATIO = {"UltraQuality": 1.0 / 1.3, "MaxQuality": 2.0 / 3.0, "Balanced": 0.58,
         "MaxPerf": 0.5, "UltraPerformance": 1.0 / 3.0}.get(PROFILE, 0.58)

m.loadScene(DATA_DIR + r"\Bistro_5_1\BistroExterior.fbx")

m.scene.addGVDBVolume(sigma_a=float3(10, 10, 10), sigma_s=float3(80, 80, 80), g=0.0,
                      dataFile=DATA_DIR + r"\smoke-plume-2", numMips=4)

m.scene.camera.position = float3(-15.149291, 8.352362, -8.399609)
m.scene.camera.target = float3(-14.742913, 8.025879, -7.546224)
m.scene.camera.up = float3(0.004061, 0.999961, 0.007782)


def render_graph():
    g = RenderGraph("Bistro DLSS-D")

    vr = createPass("VolumetricReSTIR", {
        # Ratio, not a size: the script cannot query the real window (fullscreen gives something
        # other than VR_DISPLAY), but each pass is handed it at compile time. All three passes
        # feeding RR must resolve the SAME ratio or the guides misregister.
        'upscale': UPSCALE, 'upscaleRatio': RATIO,
        # GBufferRaster owns the jitter in Stage 1, so this pass installs no pattern of its own.
        'samplePattern': 'Center',
        'mOutputDepth': False,
        'mMotionVecMode': 'Off',
        'mOutputVolumeGuides': VOLGUIDES,
        'mParams': {
            'mUseSurfaceScene': True,
            'mUseEmissiveLights': True,
            'mUseEnvironmentLights': False,
            'mTemporalReuseMThreshold': 10.0,
        }})
    g.addPass(vr, "VolumetricReSTIR")

    # Guide producer. Halton jitter is what lets RR resolve sub-pixel detail.
    gb = createPass("GBufferRaster", {'upscale': UPSCALE, 'upscaleRatio': RATIO,
                                      'samplePattern': 'Halton', 'sampleCount': 32})
    g.addPass(gb, "GBufferRaster")

    # F0 -> pre-integrated specular albedo, and roughness unpacked into its own texture.
    # sigma_s/sigma_t for the Bistro plume: 80 / (80 + 10).
    guides = createPass("DLSSDGuides", {'mediumScatterAlbedo': float3(0.888, 0.888, 0.888),
                                       'upscale': UPSCALE, 'upscaleRatio': RATIO})
    g.addPass(guides, "DLSSDGuides")

    rr = createPass("DLSSDPass", {'enabled': True, 'profile': PROFILE, 'preset': PRESET,
                                  'isHDR': True, 'motionVectorsRelative': True})
    g.addPass(rr, "DLSSDPass")

    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 8.0})
    g.addPass(tm, "ToneMapper")

    g.addEdge("GBufferRaster.diffuseOpacity", "DLSSDGuides.diffuseOpacity")
    g.addEdge("GBufferRaster.specRough", "DLSSDGuides.specRough")
    g.addEdge("GBufferRaster.guideNormalW", "DLSSDGuides.guideNormalW")
    g.addEdge("GBufferRaster.viewW", "DLSSDGuides.viewW")
    if VOLGUIDES:
        # The medium describes itself: coverage and a camera-facing stand-in normal.
        g.addEdge("VolumetricReSTIR.mediumAlpha", "DLSSDGuides.mediumAlpha")
        g.addEdge("VolumetricReSTIR.mediumNormal", "DLSSDGuides.mediumNormal")

    # RR consumes linear HDR radiance, so the ToneMapper stays last.
    g.addEdge("VolumetricReSTIR.accumulated_color", "DLSSDPass.color")
    g.addEdge("GBufferRaster.linearZ", "DLSSDPass.depth")
    g.addEdge("GBufferRaster.mvec", "DLSSDPass.mvec")
    g.addEdge("DLSSDGuides.diffuseAlbedo", "DLSSDPass.diffuseAlbedo")
    g.addEdge("DLSSDGuides.specularAlbedo", "DLSSDPass.specularAlbedo")
    g.addEdge("DLSSDGuides.normals", "DLSSDPass.normals")
    g.addEdge("DLSSDGuides.roughness", "DLSSDPass.roughness")
    g.addEdge("DLSSDPass.output", "ToneMapper.src")

    g.markOutput("ToneMapper.dst")
    # Marked so every guide can be inspected in Mogwai's output dropdown (V2 of the ladder).
    g.markOutput("DLSSDGuides.diffuseAlbedo")
    g.markOutput("DLSSDGuides.specularAlbedo")
    g.markOutput("DLSSDGuides.normals")
    g.markOutput("DLSSDGuides.roughness")
    if VOLGUIDES:
        g.markOutput("VolumetricReSTIR.mediumAlpha")
    return g


print("[dlssd] bistro profile=" + PROFILE + " preset=" + PRESET
      + " volGuides=" + ("on" if VOLGUIDES else "off")
      + " render=" + str(RENDER[0]) + "x" + str(RENDER[1])
      + " display=" + str(DISPLAY[0]) + "x" + str(DISPLAY[1]))

m.addGraph(render_graph())
m.resizeSwapChain(DISPLAY[0], DISPLAY[1])
m.ui = True

_cap = int(os.environ.get("VR_CAPTURE_FRAME", "0"))
if _cap > 0:
    _out = os.environ.get("VR_OUT_DIR", r"C:\research\Denoising-VolumetricReSTIR\shots\dlssd")
    os.makedirs(_out, exist_ok=True)
    m.frameCapture.outputDir = _out
    m.frameCapture.baseFilename = os.environ.get("VR_TAG", "dlssd")
    m.frameCapture.addFrames(m.activeGraph, [_cap])
