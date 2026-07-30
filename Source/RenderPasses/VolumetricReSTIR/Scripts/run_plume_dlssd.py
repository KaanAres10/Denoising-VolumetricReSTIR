# Plume + DLSS Ray Reconstruction with VOLUMETRIC guides (Stage 2).
#
# The decisive Stage 2 test. On Bistro the medium covers only part of the frame and the surface
# guides dominate, so the volumetric blend was lost in run-to-run noise. Here there is no geometry
# at all beyond a ground plane -- alpha is ~1 across the plume, so the guides RR sees ARE the
# volumetric ones. A GBuffer is still present because RR requires depth/mvec and the guide inputs,
# but on the plume it reports "everything at the far plane", which is exactly the limitation the
# volumetric guides exist to fix.
#
#   VR_VOLGUIDES=0   surface-only guides, for the A/B
#   VR_PROFILE=DLAA  native resolution
#
# Run:  Mogwai.exe --script run_plume_dlssd.py


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

m.loadScene(DATA_DIR + r"\default.obj")
m.scene.setEnvMap(DATA_DIR + r"\hansaplatz_8k.hdr")

m.scene.addGVDBVolume(
    sigma_a=float3(6, 6, 6), sigma_s=float3(14, 14, 14), g=0.0,
    dataFile=DATA_DIR + r"\fire115\fire115.0198",
    numMips=4, densityScale=0.1, hasVelocity=False, hasEmission=False, LeScale=0.01,
    temperatureCutoff=900.0, temperatureScale=0.0,
    worldTranslation=float3(0, 1.686, 0), worldRotation=float3(0, 0, 0), worldScaling=0.013)

m.scene.camera.position = float3(1.977354, 2.411630, 2.242076)
m.scene.camera.target = float3(1.366226, 2.220231, 1.474033)
m.scene.camera.up = float3(0.0, 1.0, 0.0)


def render_graph():
    g = RenderGraph("Plume DLSS-D")

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
            'mEnableTemporalReuse': True,
            'mEnableSpatialReuse': True,
            'mUseEnvironmentLights': True,
            'mUseEmissiveLights': False,
        }})
    g.addPass(vr, "VolumetricReSTIR")

    # Guide producer. Halton jitter is what lets RR resolve sub-pixel detail.
    gb = createPass("GBufferRaster", {'upscale': UPSCALE, 'upscaleRatio': RATIO,
                                      'samplePattern': 'Halton', 'sampleCount': 32})
    g.addPass(gb, "GBufferRaster")

    # F0 -> pre-integrated specular albedo, and roughness unpacked into its own texture.
    # sigma_s/sigma_t for the fire115 plume: 14 / (14 + 6).
    guides = createPass("DLSSDGuides", {'mediumScatterAlbedo': float3(0.7, 0.7, 0.7),
                                       'upscale': UPSCALE, 'upscaleRatio': RATIO})
    g.addPass(guides, "DLSSDGuides")

    rr = createPass("DLSSDPass", {'enabled': True, 'profile': PROFILE, 'preset': PRESET,
                                  'isHDR': True, 'motionVectorsRelative': True})
    g.addPass(rr, "DLSSDPass")

    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 0.0})
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


print("[dlssd] plume profile=" + PROFILE + " preset=" + PRESET
      + " volGuides=" + ("on" if VOLGUIDES else "off")
      + " render=" + str(RENDER[0]) + "x" + str(RENDER[1])
      + " display=" + str(DISPLAY[0]) + "x" + str(DISPLAY[1]))

m.addGraph(render_graph())
m.resizeSwapChain(DISPLAY[0], DISPLAY[1])
m.ui = True

_cap = int(os.environ.get("VR_CAPTURE_FRAME", "0"))
if _cap > 0:
    _out = os.environ.get("VR_OUT_DIR", r"C:\research\Denoising-VolumetricReSTIR\shots\dlssd_plume")
    os.makedirs(_out, exist_ok=True)
    m.frameCapture.outputDir = _out
    m.frameCapture.baseFilename = os.environ.get("VR_TAG", "dlssd")
    m.frameCapture.addFrames(m.activeGraph, [_cap])
