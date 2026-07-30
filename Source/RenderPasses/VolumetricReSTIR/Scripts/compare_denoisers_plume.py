# V11: every denoiser measured against a converged ground truth, on one scene, in HDR.
#
# TV (adjacent-pixel difference) only measures smoothness, so an over-blurred image scores well on
# it. The honest metric is error against a converged reference, and it must be computed on HDR data
# -- comparing tone-mapped PNGs clamps fireflies at 255 and discards energy in proportion to
# variance, which systematically flatters whichever estimator is noisier.
#
# Every mode below marks the SAME pre-tonemap HDR output, so the images are directly comparable.
#
#   VR_MODE=reference   brute-force volumetric path tracing, accumulated -> the ground truth
#   VR_MODE=none        raw ReSTIR, single frame
#   VR_MODE=oidn        + OIDN GPU
#   VR_MODE=optix       + OptiX (temporal, fed motion vectors)
#   VR_MODE=rr          + DLSS Ray Reconstruction (DLAA, volumetric guides)
#   VR_MODE=rr_upscale  + DLSS RR rendering at 58% of the pixels and reconstructing to full res.
#                       THE fixed-compute-budget datum: does RR upscaled from a 1112x626 render beat
#                       a conventional denoiser at full 1920x1080? Output is the same size as the
#                       reference either way, so the MSE is directly comparable.
#
#   VR_FRAMES=N         frames before capture (reference wants thousands; denoisers want ~200)
#
# Run:  VR_MODE=reference VR_FRAMES=2048 Mogwai.exe --script compare_denoisers_plume.py
#       VR_MODE=rr        VR_FRAMES=200  Mogwai.exe --script compare_denoisers_plume.py

import os

from falcor import *

DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"
MODE = os.environ.get("VR_MODE", "none").lower()
FRAMES = int(os.environ.get("VR_FRAMES", "200"))
OUT_DIR = os.environ.get("VR_OUT_DIR", r"C:\research\Denoising-VolumetricReSTIR\shots\v11")
RES = (1920, 1080)

IS_REFERENCE = MODE == "reference"
IS_RR = MODE in ("rr", "rr_upscale")

# Swept by sweep_rr.py. PROFILE sets BOTH the render ratio and the DLSS profile -- they must agree or
# RR reconstructs from a ratio it was not tuned for. PRESET is the denoising network: for Ray
# Reconstruction only Default/D/E exist (D = default transformer, E = latest); F..O are documented
# "do not use", and A/B/C were removed.
PROFILE = os.environ.get("VR_PROFILE", "Balanced")
PRESET = os.environ.get("VR_PRESET", "E")
# The pass names presets descriptively; a plain letter still works here. Both live RR models are
# transformer-based -- the CNN networks are the presets NVIDIA removed, so there is no CNN option.
PRESET_ENUM = {"Default": "Default", "D": "D_Transformer",
               "E": "E_TransformerLatest"}.get(PRESET, PRESET)
_RATIO = {"UltraQuality": 1.0 / 1.3, "MaxQuality": 2.0 / 3.0, "Balanced": 0.58,
          "MaxPerf": 0.5, "UltraPerformance": 1.0 / 3.0}.get(PROFILE, 0.58)
RENDER = (int(RES[0] * _RATIO) // 2 * 2, int(RES[1] * _RATIO) // 2 * 2) if MODE == "rr_upscale" else RES

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
    g = RenderGraph("V11 " + MODE)

    needs_rr = IS_RR
    vr = createPass("VolumetricReSTIR", {
        # Render below display resolution for the upscale row; identical graph otherwise.
        'outputSize': 'Fixed' if MODE == 'rr_upscale' else 'Default',
        'fixedOutputSize': RENDER,
        # RR needs jitter; nothing else does, and jitter changes what is being estimated, so it is
        # enabled only for the row that requires it.
        'samplePattern': 'Halton' if needs_rr else 'Center',
        'sampleCount': 32,
        'mOutputVolumeGuides': needs_rr,
        'mParams': {
            'mUseEnvironmentLights': True,
            'mUseEmissiveLights': False,
            'mUseReference': IS_REFERENCE,
            'mEnableTemporalReuse': not IS_REFERENCE,
            'mEnableSpatialReuse': not IS_REFERENCE,
        }})
    g.addPass(vr, "VolumetricReSTIR")

    if IS_REFERENCE:
        # Ground truth: accumulate brute-force path tracing, no denoiser.
        g.addPass(createPass("AccumulatePass", {'enabled': True}), "Accum")
        g.addEdge("VolumetricReSTIR.accumulated_color", "Accum.input")
        g.markOutput("Accum.output")
        return g

    if MODE == "none":
        g.markOutput("VolumetricReSTIR.accumulated_color")
        return g

    if MODE in ("oidn", "optix"):
        # (full resolution -- these do not upscale)
        name = "OIDNGPUPass" if MODE == "oidn" else "OptixDenoiser"
        g.addPass(createPass(name), "Denoiser")
        di, do = ("color", "output") if MODE == "optix" else ("src", "dst")
        g.addEdge("VolumetricReSTIR.accumulated_color", "Denoiser." + di)
        if MODE == "optix":
            # Motion vectors switch OptiX to its TEMPORAL model; without them it denoises each
            # frame independently. The pass negates and scales them itself (OptiX points forward
            # in time, Falcor points current->previous).
            g.addPass(createPass("GBufferRaster", {'samplePattern': 'Center'}), "GBufferRaster")
            g.addEdge("GBufferRaster.mvec", "Denoiser.mvec")
        g.markOutput("Denoiser." + do)
        return g

    # rr
    g.addPass(createPass("GBufferRaster", {'outputSize': 'Fixed' if MODE == 'rr_upscale' else 'Default',
                                           'fixedOutputSize': RENDER,
                                           'samplePattern': 'Halton', 'sampleCount': 32}), "GBufferRaster")
    # The guides MUST be allocated at the render resolution. Left at the graph default they come out
    # at swapchain size, and RR then samples guides misregistered by the upscale factor -- silent,
    # and it corrupted every upscaled row measured before this was fixed.
    g.addPass(createPass("DLSSDGuides", {'mediumScatterAlbedo': float3(0.7, 0.7, 0.7),
                                         'outputSize': 'Fixed', 'fixedOutputSize': RENDER}), "DLSSDGuides")
    # Profile must match the actual ratio: DLAA is native, Balanced is the ~58% render.
    g.addPass(createPass("DLSSDPass", {'enabled': True,
                                       'profile': PROFILE if MODE == 'rr_upscale' else 'DLAA',
                                       'preset': PRESET_ENUM, 'isHDR': True,
                                       'motionVectorsRelative': True}), "DLSSDPass")
    g.addEdge("GBufferRaster.diffuseOpacity", "DLSSDGuides.diffuseOpacity")
    g.addEdge("GBufferRaster.specRough", "DLSSDGuides.specRough")
    g.addEdge("GBufferRaster.guideNormalW", "DLSSDGuides.guideNormalW")
    g.addEdge("GBufferRaster.viewW", "DLSSDGuides.viewW")
    g.addEdge("VolumetricReSTIR.mediumAlpha", "DLSSDGuides.mediumAlpha")
    g.addEdge("VolumetricReSTIR.mediumNormal", "DLSSDGuides.mediumNormal")
    g.addEdge("VolumetricReSTIR.accumulated_color", "DLSSDPass.color")
    g.addEdge("GBufferRaster.linearZ", "DLSSDPass.depth")
    g.addEdge("GBufferRaster.mvec", "DLSSDPass.mvec")
    g.addEdge("DLSSDGuides.diffuseAlbedo", "DLSSDPass.diffuseAlbedo")
    g.addEdge("DLSSDGuides.specularAlbedo", "DLSSDPass.specularAlbedo")
    g.addEdge("DLSSDGuides.normals", "DLSSDPass.normals")
    g.addEdge("DLSSDGuides.roughness", "DLSSDPass.roughness")
    g.markOutput("DLSSDPass.output")
    return g


print("[v11] mode=" + MODE + " frames=" + str(FRAMES)
      + (" profile=" + PROFILE + " preset=" + PRESET if IS_RR else "")
      + " render=" + str(RENDER[0]) + "x" + str(RENDER[1]))

m.addGraph(render_graph())
m.resizeSwapChain(RES[0], RES[1])
m.ui = True

os.makedirs(OUT_DIR, exist_ok=True)
m.frameCapture.outputDir = OUT_DIR
# Tagged per configuration so a sweep does not overwrite itself.
m.frameCapture.baseFilename = os.environ.get(
    "VR_TAG", "v11_" + MODE + ("_" + PROFILE + "_" + PRESET if IS_RR else ""))
m.frameCapture.addFrames(m.activeGraph, [FRAMES])

# Exit on its own so a sweep does not have to wait out a timeout per cell. The margin matters:
# Texture::captureToFile writes asynchronously, and quitting the instant the capture is requested
# truncates the file.
if os.environ.get("VR_EXIT_AFTER_CAPTURE", "0") not in ("0", "", "false", "False"):
    m.clock.exitFrame = FRAMES + 60
