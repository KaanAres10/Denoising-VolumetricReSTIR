# Volumetric ReSTIR — bunny_cloud demo, ported to Falcor 8.0.
#
# Prerequisites:
#   1. The scene data (default.obj, green_sanctuary_8k.hdr, bunny_cloud/*.vbx) must exist.
#      Adjust DATA_DIR below to point at your "Data" folder.
#   2. The GVDB volume must be pre-baked to a .bin (see Source/Tools/GVDBBake). Falcor loads the
#      baked "<dataFile>.bin" instead of calling gvdb.dll (whose OpenVDB conflicts with Falcor's):
#        GVDBBake.exe "<DATA_DIR>/bunny_cloud" 7 0 0 "<DATA_DIR>/bunny_cloud.bin"
#
# Run:  Mogwai.exe --script run_bunny_cloud.py     (or drag into a running Mogwai)

from falcor import *

DATA_DIR = r"C:\Users\aresk\Desktop\Falcor\Denoising-VolumetricReSTIR\Bin\x64\Release\Data"

m.loadScene(DATA_DIR + r"\default.obj")
m.scene.setEnvMap(DATA_DIR + r"\green_sanctuary_8k.hdr")

# Static Stanford-bunny cloud. Falcor reads the pre-baked "<dataFile>.bin" next to this folder.
m.scene.addGVDBVolume(sigma_a=float3(1, 1, 1), sigma_s=float3(9, 9, 9), g=0.0,
                      dataFile=DATA_DIR + r"\bunny_cloud",
                      numMips=7, densityScale=1.0, hasVelocity=False, hasEmission=False, LeScale=1.0)

# Camera framing the bunny cloud.
m.scene.camera.position = float3(-17.290087, 23.748606, 45.495544)
m.scene.camera.target = float3(-17.053705, 23.593506, 44.536343)
m.scene.camera.up = float3(0.003480, 0.999892, -0.014248)


def render_graph():
    g = RenderGraph("Volumetric ReSTIR")
    vr = createPass("VolumetricReSTIR", {'mParams': {
        'mEnableTemporalReuse': True,
        'mEnableSpatialReuse': True,
        'mUseEnvironmentLights': True,
        'mUseEmissiveLights': False,
    }})
    g.addPass(vr, "VolumetricReSTIR")
    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 0.0})
    g.addPass(tm, "ToneMapper")
    g.addEdge("VolumetricReSTIR.accumulated_color", "ToneMapper.src")
    g.markOutput("ToneMapper.dst")
    g.markOutput("VolumetricReSTIR.mvec")  # temporal reuse binds the motion-vector output
    return g


m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True
