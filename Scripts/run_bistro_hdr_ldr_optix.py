# ============================================================
# Volumetric ReSTIR OptiX (HDR vs LDR) / Reference
# - LDR: adds a 2nd ToneMapper after OptiX 
# ============================================================

from falcor import *
import os

# CONFIG
PIPE_MODE    = "REF"        # "HDR" | "LDR" | "REF"
CAPTURE_MODE = "frames"     # "timing" | "frames" | "both"
USE_TEMPORAL = False     

W, H = 1920, 1080
NUM_FRAMES = 100            # used for HDR/LDR; REF will override to 1 below


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

OUT_ROOT = os.path.join(
    SCRIPT_DIR,
    "outputs",
    "Bistro_Optix_HDR_LDR"
)
OUT_DIR  = os.path.join(OUT_ROOT, PIPE_MODE)  # HDR / LDR / REF
BASE     = PIPE_MODE.lower()

os.makedirs(OUT_DIR, exist_ok=True)

# Reference quality (only used in REF)
BASELINE_SPP = 20
ACCUM_FRAMES = 1000         

# Force single-frame output for reference
if PIPE_MODE == "REF":
    NUM_FRAMES = 1


def make_optix_params():
    if USE_TEMPORAL:
        model = 4
    else:
        model = 1 if PIPE_MODE == "HDR" else 0  # 1=HDR, 0=LDR
    return {"enabled": True, "blend": 0.0, "denoiseAlpha": False, "model": model}

def make_tonemapper_primary():
    return createPass("ToneMapper", {
        "operator": ToneMapOp.Linear,
        "autoExposure": False,
        "exposureCompensation": 8.0,
        "exposureValue": 0.0,
        "clamp": True,
        "filmSpeed": 100.0,
        "whiteBalance": False,
        "whitePoint": 6500.0,
        "whiteMaxLuminance": 1.0,
        "whiteScale": 1.0,
        "fNumber": 1.0,
        "shutter": 1.0,
        "exposureMode": ExposureMode.AperturePriority,
    })

def make_tonemapper_writeout():
    """
    2nd ToneMapper only for LDR path
    """
    return createPass("ToneMapper", {
        "operator": ToneMapOp.Linear,
        "autoExposure": False,
        "exposureCompensation": 0.0,   # IMPORTANT: don't re-expose here
        "exposureValue": 0.0,
        "clamp": True,

        # keep neutral settings
        "filmSpeed": 100.0,
        "whiteBalance": False,
        "whitePoint": 6500.0,
        "whiteMaxLuminance": 1.0,
        "whiteScale": 1.0,
        "fNumber": 1.0,
        "shutter": 1.0,
        "exposureMode": ExposureMode.AperturePriority,
    })

def render_graph():
    g = RenderGraph(f"Pipe {PIPE_MODE}")

    loadRenderPassLibrary("AccumulatePass.dll")
    loadRenderPassLibrary("VolumetricReSTIR.dll")
    loadRenderPassLibrary("ToneMapper.dll")

    # REF PATH 
    if PIPE_MODE == "REF":
        params = VolumetricReSTIRParams(
            mUseReference=True,
            mBaselineSamplePerPixel=BASELINE_SPP,

            mEnableTemporalReuse=False,
            mEnableSpatialReuse=False,
            mVertexReuse=False,

            mUseSurfaceScene=True,
            mUseEmissiveLights=True,
            mUseEnvironmentLights=False,
            mTemporalReuseMThreshold=10.0
        )

        ReSTIR = createPass("VolumetricReSTIR", {"mParams": params})

        Acc = createPass("AccumulatePass", {
            "enableAccumulation": True,
            "autoReset": False,
        })

        TM = make_tonemapper_primary()

        g.addPass(ReSTIR, "ReSTIR")
        g.addPass(Acc,   "Acc")
        g.addPass(TM,    "TM")

        g.addEdge("ReSTIR.accumulated_color", "Acc.input")
        g.addEdge("Acc.output",              "TM.src")
        g.markOutput("TM.dst")
        return g

    # HDR/LDR PATH 
    loadRenderPassLibrary("OptixDenoiserRecent.dll")

    ReSTIR = createPass("VolumetricReSTIR", {
        "mParams": VolumetricReSTIRParams(
            mUseSurfaceScene=True,
            mUseEmissiveLights=True,
            mUseEnvironmentLights=False,
            mTemporalReuseMThreshold=10.0
        )
    })

    Acc   = createPass("AccumulatePass", {"enableAccumulation": False})
    Optx  = createPass("OptixDenoiserRecent", make_optix_params())
    TM1   = make_tonemapper_primary()

    g.addPass(ReSTIR, "ReSTIR")
    g.addPass(Acc,   "Acc")
    g.addPass(Optx,  "Optix")
    g.addPass(TM1,   "TM1")

    if PIPE_MODE == "HDR":
        # HDR: OptiX BEFORE ToneMapper
        g.addEdge("ReSTIR.accumulated_color", "Acc.input")
        g.addEdge("Acc.output",              "Optix.color")
        if USE_TEMPORAL:
            g.addEdge("ReSTIR.mvec", "Optix.mvec")
        g.addEdge("Optix.output",            "TM1.src")
        g.markOutput("TM1.dst")

    else:
        # LDR: ToneMapper first, then OptiX(LDR model),
        # THEN ToneMapper2 for write-out
        TM2 = make_tonemapper_writeout()
        g.addPass(TM2, "TM2")

        g.addEdge("ReSTIR.accumulated_color", "Acc.input")
        g.addEdge("Acc.output",              "TM1.src")
        g.addEdge("TM1.dst",                 "Optix.color")
        if USE_TEMPORAL:
            g.addEdge("ReSTIR.mvec", "Optix.mvec")

        # OptiX -> TM2 -> output
        g.addEdge("Optix.output",            "TM2.src")
        g.markOutput("TM2.dst")

    return g


# SCENE 
m.loadScene("Bistro_5_1/BistroExterior.fbx")
m.scene.setEnvMap("skylight-morn.exr")
m.scene.setEnvMapRotation(float3(0, 72.5, 0))
m.scene.setEnvMapIntensity(0)

m.addGVDBVolume(
    sigma_a=float3(10,10,10),
    sigma_s=float3(80,80,80),
    g=0.0,
    dataFile="smoke-plume-2",
    numMips=4
)

m.scene.animated = False
m.scene.camera.animated = False
m.scene.camera.position = float3(-15.149291, 8.352362, -8.399609)
m.scene.camera.target   = float3(-14.742913, 8.025879, -7.546224)
m.scene.camera.up       = float3(0.004061, 0.999961, 0.007782)
m.scene.cameraSpeed     = 1.0


graph = render_graph()
m.addGraph(graph)

m.resizeSwapChain(W, H)
m.ui = False
fc.ui = False

t.time = 0
t.framerate = 0


# CAPTURE MODE 
if CAPTURE_MODE in ("timing", "both"):
    tc.captureFrameTime(os.path.join(OUT_DIR, "frame_times.csv"))

if CAPTURE_MODE in ("frames", "both"):
    fc.outputDir = OUT_DIR

print(f"PIPE_MODE    = {PIPE_MODE}")
print(f"CAPTURE_MODE = {CAPTURE_MODE}")
print(f"OUT_DIR      = {OUT_DIR}")
print(f"NUM_FRAMES   = {NUM_FRAMES}")
if PIPE_MODE == "REF":
    print(f"REF: BASELINE_SPP={BASELINE_SPP}, ACCUM_FRAMES={ACCUM_FRAMES} => effective ~{BASELINE_SPP * ACCUM_FRAMES} spp/frame")

# Get accumulation pass handle for REF
accumPass = None
if PIPE_MODE == "REF":
    accumPass = m.activeGraph.getPass("Acc")


# MAIN LOOP 
for i in range(NUM_FRAMES):
    if PIPE_MODE == "REF":
        accumPass.reset()
        for _ in range(ACCUM_FRAMES):
            renderFrame()
    else:
        renderFrame()

    if CAPTURE_MODE in ("frames", "both"):
        fc.baseFilename = f"{BASE}_{i:04d}"
        fc.capture()

print("Done.")
exit()
