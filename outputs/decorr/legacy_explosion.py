# The legacy (Falcor 4) build rendering legacy run_LGHExplosion.py as written, plus a capture: the ground truth
# for the port's explosiondusk. Run from legacy/Bin/x64/Release with
# FALCOR_MEDIA_FOLDERS=<repo>/VolumetricReSTIRData;<repo>/legacy/Media.
# LEG_OUT (absolute dir), LEG_FRAMES (accumulated frames), LEG_BOUNCES (the script's 2), LEG_TSCALE, LEG_LESCALE.
from falcor import *
import os
OUT = os.environ["LEG_OUT"]
TSCALE = float(os.environ.get("LEG_TSCALE", "750"))
LESCALE = float(os.environ.get("LEG_LESCALE", "1"))
FRAMES = int(os.environ.get("LEG_FRAMES", "64"))
BOUNCES = int(os.environ.get("LEG_BOUNCES", "2"))

def render_graph():
    g = RenderGraph("Volumetric ReSTIR")
    loadRenderPassLibrary("AccumulatePass.dll")
    loadRenderPassLibrary("VolumetricReSTIR.dll")
    g.addPass(createPass("VolumetricReSTIR", {"mParams": VolumetricReSTIRParams(mMaxBounces=BOUNCES)}), "VolumetricReSTIR")
    g.addPass(createPass("AccumulatePass", {"enableAccumulation": True}), "AccumulatePass")
    g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
    g.markOutput("AccumulatePass.output")
    return g

m.loadScene("default.obj")
m.scene.setEnvMap("skylight-dusk.exr")
m.scene.setEnvMapRotation(float3(13,136,340))
m.addGVDBVolume(sigma_a=float3(10,10,10), sigma_s=float3(10,10,10), g=0.0, dataFile="LGHExplosion/LGHExplosion.183", numMips=4, densityScale = 0.02, hasVelocity=False, hasEmission=True, LeScale=LESCALE, temperatureCutoff = 0.0, temperatureScale = TSCALE)
m.scene.camera.position = float3(-29.487331,10.408340,0.493491)
m.scene.camera.target = float3(-28.505859,10.597045,0.460278)
m.scene.camera.up = float3(-0.000909,1.000000,0.000030)
m.addGraph(render_graph())
m.resizeSwapChain(960, 540)
m.ui = False
fc.ui = False
t.pause()
t.frame = 0
fc.outputDir = OUT
for i in range(FRAMES):
    renderFrame()
fc.baseFilename = "legacy_t%d_le%g" % (TSCALE, LESCALE)
fc.capture()
exit()
