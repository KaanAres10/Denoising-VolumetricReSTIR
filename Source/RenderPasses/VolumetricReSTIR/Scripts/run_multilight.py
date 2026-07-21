# Volumetric ReSTIR — bunny_cloud volume lit by MULTIPLE analytic point lights (Falcor 8.0).
#
# Demonstrates multi-light volumetric ReSTIR: the participating medium is lit by several colored
# point lights (no environment / emissive), each contributing directional colored scattering.
#
# It loads a small .pyscene that imports the existing default.obj ground plane and adds the lights
# (analytic lights can't be added to an already-loaded scene at runtime, so they live in the
# .pyscene). Create "<DATA_DIR>/bunny_multilight.pyscene" with:
#
#   sceneBuilder.importScene('default.obj')
#   def addPoint(n, i, p):
#       L = PointLight(n); L.intensity = i; L.position = p; sceneBuilder.addLight(L)
#   addPoint('key_red',    float3(9000, 1200, 1200), float3(35, 34, 34))
#   addPoint('fill_green', float3(1200, 9000, 1600), float3(-38, 28, 30))
#   addPoint('rim_blue',   float3(1500, 1800, 12000), float3(-6, 58, -14))
#   addPoint('warm_front', float3(9000, 6500, 3500), float3(-4, 12, 48))
#   camera = Camera()
#   camera.position = float3(-17.290087, 23.748606, 45.495544)
#   camera.target   = float3(-17.053705, 23.593506, 44.536343)
#   camera.up       = float3(0.003480, 0.999892, -0.014248)
#   sceneBuilder.addCamera(camera)
#
# Run:  Mogwai.exe --script run_multilight.py

from falcor import *

DATA_DIR = r"C:\Users\aresk\Desktop\Falcor\Denoising-VolumetricReSTIR\Bin\x64\Release\Data"

m.loadScene(DATA_DIR + r"\bunny_multilight.pyscene")
m.scene.addGVDBVolume(sigma_a=float3(1, 1, 1), sigma_s=float3(9, 9, 9), g=0.0,
                      dataFile=DATA_DIR + r"\bunny_cloud",
                      numMips=7, densityScale=1.0, hasVelocity=False, hasEmission=False, LeScale=1.0)


def render_graph():
    g = RenderGraph("Volumetric ReSTIR multi-light")
    vr = createPass("VolumetricReSTIR", {'mParams': {
        'mUseAnalyticLights': True,     # <-- light the volume with the scene's point lights
        'mUseEmissiveLights': False,
        'mUseEnvironmentLights': False,
        'mEnableTemporalReuse': True,
        'mEnableSpatialReuse': True,
    }})
    g.addPass(vr, "VolumetricReSTIR")
    acc = createPass("AccumulatePass", {'enabled': True})
    g.addPass(acc, "AccumulatePass")
    tm = createPass("ToneMapper", {'autoExposure': False})
    g.addPass(tm, "ToneMapper")
    g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
    g.addEdge("AccumulatePass.output", "ToneMapper.src")
    g.markOutput("ToneMapper.dst")
    g.markOutput("VolumetricReSTIR.mvec")
    return g


m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True
