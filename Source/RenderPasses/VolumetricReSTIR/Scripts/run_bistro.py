# Volumetric ReSTIR — Bistro (surface scene + smoke plume + many emissive lights), Falcor 8.0 port.
#
# This is the paper-style figure: the Bistro exterior geometry lit by its hundreds of emissive lights
# (street lamps + colored string bulbs), with a participating-medium smoke plume scattering that light
# (blue from the cyan bulbs, magenta/pink from the magenta ones).
#
# Prerequisites:
#   1. Scene data: Bistro_5_1/BistroExterior.fbx and smoke-plume-2/ under DATA_DIR.
#   2. The volume must be pre-baked to a .bin (see Source/Tools/GVDBBake); Falcor loads
#      "<dataFile>.bin" instead of calling gvdb.dll:
#        GVDBBake.exe "<DATA_DIR>\smoke-plume-2" 4 0 0 "<DATA_DIR>\smoke-plume-2.bin"
#
# NOTE: keep the volume parameters below as-is. sigma_s=80 is what gives the plume its density,
# structure and colored scattering — thinning it out washes both the detail and the color away.
#
# Run:  Mogwai.exe --script run_bistro.py

from falcor import *

DATA_DIR = r"C:\Users\aresk\Desktop\Falcor\Denoising-VolumetricReSTIR\Bin\x64\Release\Data"

m.loadScene(DATA_DIR + r"\Bistro_5_1\BistroExterior.fbx")

# Dense smoke plume (fork's original parameters).
m.scene.addGVDBVolume(sigma_a=float3(10, 10, 10), sigma_s=float3(80, 80, 80), g=0.0,
                      dataFile=DATA_DIR + r"\smoke-plume-2", numMips=4)

m.scene.camera.position = float3(-15.149291, 8.352362, -8.399609)
m.scene.camera.target = float3(-14.742913, 8.025879, -7.546224)
m.scene.camera.up = float3(0.004061, 0.999961, 0.007782)


def render_graph():
    g = RenderGraph("Volumetric ReSTIR Bistro")
    vr = createPass("VolumetricReSTIR", {'mParams': {
        'mUseSurfaceScene': True,        # shade the Bistro geometry (surface-scene path)
        'mUseEmissiveLights': True,      # the scene's many emissive lights
        'mUseEnvironmentLights': False,  # night scene, no sky contribution
        'mTemporalReuseMThreshold': 10.0,
    }})
    g.addPass(vr, "VolumetricReSTIR")
    acc = createPass("AccumulatePass", {'enabled': True})
    g.addPass(acc, "AccumulatePass")
    # NOTE: don't pass operator=ToneMapOp.Aces here — that enum access throws from a script.
    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 8.0})
    g.addPass(tm, "ToneMapper")
    g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
    g.addEdge("AccumulatePass.output", "ToneMapper.src")
    g.markOutput("ToneMapper.dst")
    g.markOutput("VolumetricReSTIR.mvec")
    return g


m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True
