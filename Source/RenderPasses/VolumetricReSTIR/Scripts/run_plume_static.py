# Volumetric ReSTIR — single frozen frame of the fire115 plume, ported to Falcor 8.0.
#
# Same scene as run_plume.py but with one static volume instead of the animated sequence: frame 0198
# loaded on its own, with velocity off (a still frame has nothing to reproject from).
#
# Faithful to the Falcor 4.x script of the same name: identical volume parameters, scene, env map and
# camera, with mOutputMotionVec and accumulation-off preserved. The one addition is a ToneMapper --
# the 4.x graph marked AccumulatePass.output and sent raw HDR to the screen, so absolute brightness
# will not match the old output pixel for pixel.
#
# Because the volume is static, ticking "enabled" on the AccumulatePass in the UI converges to a
# clean still -- the ground-truth reference for judging a denoiser on this scene.
#
# Prerequisites:
#   1. Scene data (default.obj, hansaplatz_8k.hdr, fire115/fire115.0198/*.vbx). Adjust DATA_DIR below.
#   2. The volume must be pre-baked to a .bin (see Source/Tools/GVDBBake). Note the bake flags must
#      match the load flags -- this frame is baked WITHOUT velocity:
#        GVDBBake.exe "<DATA_DIR>\fire115\fire115.0198" 4 0 0 "<DATA_DIR>\fire115\fire115.0198.bin"
#
# Run:  Mogwai.exe --script run_plume_static.py
#       (or VS Code -> Run Task -> "Run: plume (static frame)")

from falcor import *

DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"

# Which pre-baked frame to freeze on. Any frame works as long as its .bin exists and was baked with
# the same numMips / hasVelocity / hasEmission flags used below.
FRAME = "fire115.0198"

m.loadScene(DATA_DIR + r"\default.obj")
m.scene.setEnvMap(DATA_DIR + r"\hansaplatz_8k.hdr")

# Single static frame of the plume. Parameters are the fork's originals; hasVelocity=False because
# there is no previous frame to reproject against.
m.scene.addGVDBVolume(
    sigma_a=float3(6, 6, 6), sigma_s=float3(14, 14, 14), g=0.0,
    dataFile=DATA_DIR + "\\fire115\\" + FRAME,
    numMips=4, densityScale=0.1,
    hasVelocity=False, hasEmission=False, LeScale=0.01,
    temperatureCutoff=900.0, temperatureScale=0.0,
    worldTranslation=float3(0, 1.686, 0), worldRotation=float3(0, 0, 0), worldScaling=0.013)

m.scene.cameraSpeed = 1
m.scene.camera.position = float3(1.977354, 2.411630, 2.242076)
m.scene.camera.target = float3(1.366226, 2.220231, 1.474033)
m.scene.camera.up = float3(0.0, 1.0, 0.0)


def render_graph():
    g = RenderGraph("Volumetric ReSTIR plume (static)")
    # mOutputMotionVec matches the 4.x script; it is what makes VolumetricReSTIR.mvec usable as a
    # denoiser input (the fork's run_plume_denoiser.py fed it to OptixDenoiser.mvec).
    vr = createPass("VolumetricReSTIR", {
        'mOutputMotionVec': True,
        'mParams': {
            'mEnableTemporalReuse': True,
            'mEnableSpatialReuse': True,
            'mUseEnvironmentLights': True,
            'mUseEmissiveLights': False,
        }})
    g.addPass(vr, "VolumetricReSTIR")
    # Accumulation off, as in the 4.x script: you see the raw per-frame ReSTIR estimate. Because the
    # volume is static, ticking "enabled" on this pass in the UI converges it to a clean still --
    # which is how you get a ground-truth reference for judging a denoiser on this scene.
    acc = createPass("AccumulatePass", {'enabled': False})
    g.addPass(acc, "AccumulatePass")
    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 0.0})
    g.addPass(tm, "ToneMapper")
    g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
    g.addEdge("AccumulatePass.output", "ToneMapper.src")
    g.markOutput("ToneMapper.dst")
    g.markOutput("VolumetricReSTIR.mvec")  # temporal reuse binds the motion-vector output
    return g


m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True
