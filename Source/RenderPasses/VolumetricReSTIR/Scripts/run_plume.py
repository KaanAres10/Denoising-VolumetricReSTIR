# Volumetric ReSTIR — animated fire/smoke plume (fire115) sequence, ported to Falcor 8.0.
#
# Prerequisites:
#   1. Scene data (default.obj, hansaplatz_8k.hdr, fire115/fire115.NNNN/*.vbx). Adjust DATA_DIR below.
#   2. Each frame of the sequence must be pre-baked to a .bin next to its frame folder (see
#      Source/Tools/GVDBBake). Falcor loads "<dataFilePrefix><NNNN>.bin" per frame instead of
#      calling gvdb.dll (whose OpenVDB conflicts with Falcor's). Bake e.g. frames 100..115:
#        for /L %n in (100,1,115) do GVDBBake.exe "<DATA_DIR>\fire115\fire115.0%n" 4 1 0 "<DATA_DIR>\fire115\fire115.0%n.bin"
#      (args: <vbxFolder> <numMips> <hasVelocity> <hasEmission> <out.bin>)
#
# The sequence advances one frame per rendered frame (Scene::update -> advanceVolumeAnimation), with
# velocity-based temporal reprojection. Set the pass property 'mVolumeAnimationSelectedFrameId' to a
# frame index (0-based) to pause on it and let ReSTIR/accumulation converge to a clean still.
#
# Run:  Mogwai.exe --script run_plume.py

from falcor import *

DATA_DIR = r"C:\Users\aresk\Desktop\Falcor\Denoising-VolumetricReSTIR\Bin\x64\Release\Data"

# How many consecutive frames have been baked, starting at START_FRAME (the fork used 100..299).
START_FRAME = 100
NUM_FRAMES = 16

m.loadScene(DATA_DIR + r"\default.obj")
m.scene.setEnvMap(DATA_DIR + r"\hansaplatz_8k.hdr")

m.scene.addGVDBVolumeSequence(
    sigma_a=float3(6, 6, 6), sigma_s=float3(14, 14, 14), g=0.0,
    dataFilePrefix=DATA_DIR + r"\fire115\fire115.", numberFixedLength=4,
    startFrame=START_FRAME, numFrames=NUM_FRAMES, numMips=4, densityScale=0.1,
    hasVelocity=True, hasEmission=False, LeScale=0.01,
    temperatureCutoff=900.0, temperatureScale=0.0,
    worldTranslation=float3(0, 1.686, 0), worldRotation=float3(0, 0, 0), worldScaling=0.013)

m.scene.camera.position = float3(1.977354, 2.411630, 2.242076)
m.scene.camera.target = float3(1.366226, 2.220231, 1.474033)
m.scene.camera.up = float3(0.0, 1.0, 0.0)


def render_graph():
    g = RenderGraph("Volumetric ReSTIR plume")
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
