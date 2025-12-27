# ============================================================
# Plume: Volumetric ReSTIR / OIDN (CPU)
# Graph: VolumetricReSTIR -> AccumulatePass -> OIDNCPUPass -> ToneMapper
# ============================================================

from falcor import *

gAccumulateParams = {
    "enableAccumulation": False
}

def render_graph():
    g = RenderGraph("Volumetric ReSTIR on OIDN(CPU)")

    loadRenderPassLibrary("AccumulatePass.dll")
    loadRenderPassLibrary("VolumetricReSTIR.dll")
    loadRenderPassLibrary("ToneMapper.dll")
    loadRenderPassLibrary("OIDNCPUPass.dll")

    VolumetricReSTIR = createPass("VolumetricReSTIR")
    AccumulatePass   = createPass("AccumulatePass", gAccumulateParams)
    OIDNPass         = createPass("OIDNCPUPass")

    ToneMapper = createPass("ToneMapper", {
        "operator": ToneMapOp.Linear,
        "autoExposure": True,
        "exposureCompensation": 2.0, 
        "clamp": True,
        "exposureValue": 0.0,
        "filmSpeed": 100.0,
        "whiteBalance": False,
        "whitePoint": 6500.0,
        "whiteMaxLuminance": 1.0,
        "whiteScale": 1.0,
        "fNumber": 1.0,
        "shutter": 1.0,
        "exposureMode": ExposureMode.AperturePriority,
    })

    g.addPass(VolumetricReSTIR, "VolumetricReSTIR")
    g.addPass(AccumulatePass,   "AccumulatePass")
    g.addPass(OIDNPass,         "OIDNPass")
    g.addPass(ToneMapper,       "ToneMapper")

    g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
    g.addEdge("AccumulatePass.output",              "OIDNPass.src")
    g.addEdge("OIDNPass.dst",                       "ToneMapper.src")

    g.markOutput("ToneMapper.dst")
    return g


m.loadScene("default.obj")
m.scene.setEnvMap("hansaplatz_8k.hdr")

m.addGVDBVolume(
    sigma_a=float3(6, 6, 6),
    sigma_s=float3(14, 14, 14),
    g=0.0,
    dataFile="fire115/fire115.0198",
    numMips=4,
    densityScale=0.1,
    hasVelocity=False,
    hasEmission=False,
    LeScale=0.01,
    temperatureCutoff=900.0,
    temperatureScale=0.0,
    worldTranslation=float3(0, 1.686, 0),
    worldRotation=float3(0, 0, 0),
    worldScaling=0.013
)

m.scene.cameraSpeed = 1
m.scene.camera.position = float3(1.977354, 2.411630, 2.242076)
m.scene.camera.target   = float3(1.366226, 2.220231, 1.474033)
m.scene.camera.up       = float3(0.0, 1.0, 0.0)

graph = render_graph()
m.addGraph(graph)

m.resizeSwapChain(1920, 1080)
m.ui = True

t.time = 0
t.framerate = 0
