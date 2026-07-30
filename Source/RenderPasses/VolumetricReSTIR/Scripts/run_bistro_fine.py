# Bistro with fine-grained volume sampling, to test whether the visible square artifacts are
# coarse-mip / point-sampling artifacts rather than a bug.
#
# The pass defaults sample the volume coarsely on purpose -- that is what makes Volumetric ReSTIR
# cheap -- but the structure becomes visible when the camera is close to the medium:
#
#     param                                default   here    effect
#     mInitialBaseMipLevel                 1         0       primary visibility at full resolution
#     mInitialLightingMipLevel             2         0       lighting at full resolution
#     mInitialVisibilityUseLinearSampler   False     True    trilinear instead of nearest -> no hard
#                                                            square edges (note the default already
#                                                            uses linear for *lighting*, not visibility)
#     mTemporalReprojectionMipLevel        1         0
#     mSpatialVisibilityMipLevel           1         0
#     mSpatialLightingMipLevel             1         0
#
# Set VR_FINE=0 to run with the stock defaults instead, for a direct A/B against the same camera.
# This is slower by design -- it is the sampling side of the sampling-vs-denoising tradeoff.
#
# Run:  Mogwai.exe --script run_bistro_fine.py
#       (or VS Code -> Run Task -> "Run: bistro (fine sampling)")

import os

from falcor import *

DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"
FINE = os.environ.get("VR_FINE", "1") not in ("0", "", "false", "False")

m.loadScene(DATA_DIR + r"\Bistro_5_1\BistroExterior.fbx")

# Dense smoke plume (fork's original parameters). sigma_s=80 is what gives the plume its density,
# structure and coloured scattering -- thinning it out washes both the detail and the colour away.
m.scene.addGVDBVolume(sigma_a=float3(10, 10, 10), sigma_s=float3(80, 80, 80), g=0.0,
                      dataFile=DATA_DIR + r"\smoke-plume-2", numMips=4)

m.scene.camera.position = float3(-15.149291, 8.352362, -8.399609)
m.scene.camera.target = float3(-14.742913, 8.025879, -7.546224)
m.scene.camera.up = float3(0.004061, 0.999961, 0.007782)


def volume_params():
    p = {
        'mUseSurfaceScene': True,        # shade the Bistro geometry (surface-scene path)
        'mUseEmissiveLights': True,      # the scene's many emissive lights
        'mUseEnvironmentLights': False,  # night scene, no sky contribution
        'mTemporalReuseMThreshold': 10.0,
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
    g = RenderGraph("Bistro" + (" (fine sampling)" if FINE else " (default sampling)"))
    vr = createPass("VolumetricReSTIR", {'mParams': volume_params()})
    g.addPass(vr, "VolumetricReSTIR")
    acc = createPass("AccumulatePass", {'enabled': True})
    g.addPass(acc, "AccumulatePass")
    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 8.0})
    g.addPass(tm, "ToneMapper")
    g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
    g.addEdge("AccumulatePass.output", "ToneMapper.src")
    g.markOutput("ToneMapper.dst")
    return g


print("[fine] volume sampling: " + ("FINE (mip 0, linear)" if FINE else "DEFAULTS (set VR_FINE=1 for fine)"))

m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True
