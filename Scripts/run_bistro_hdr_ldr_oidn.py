# ============================================================
# Volumetric ReSTIR OIDN (GPU)  (HDR vs LDR) / Reference
# - HDR:  OIDN before ToneMapper (denoise linear HDR)
# - LDR:  ToneMap first -> OIDN in LDR mode -> ToneMap writeout
# - REF:  ReSTIR reference accumulation (no denoiser by default)
# ============================================================

from falcor import *
import os
import math


# CONFIG
PIPE_MODE    = "REF"      # "HDR" | "LDR" | "REF"
CAPTURE_MODE = "frames"   # "timing" | "frames" | "both"

W, H = 1920, 1080
NUM_FRAMES = 100          # used for HDR/LDR; REF will override to 1 below

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

OUT_ROOT = os.path.join(
    SCRIPT_DIR,
    "outputs",
    "Bistro_OIDN_HDR_LDR"
)
OUT_DIR  = os.path.join(OUT_ROOT, PIPE_MODE)
BASE     = PIPE_MODE.lower()
os.makedirs(OUT_DIR, exist_ok=True)

# Reference quality (only used in REF)
BASELINE_SPP = 20
ACCUM_FRAMES = 1000       

if PIPE_MODE == "REF":
    NUM_FRAMES = 1

# ----------------------------
# OIDN params
OIDN_ENABLED     = True
OIDN_QUALITY     = 3       # 0 default, 1 fast, 2 balanced, 3 high
OIDN_MAX_MEM_MB  = -1      # -1 = auto
OIDN_INPUT_SCALE = float("nan")  # NaN = auto
OIDN_CLEAN_AUX   = False
OIDN_SRGB        = False   

def make_oidn_params():
    return {
        "mEnabled": OIDN_ENABLED,
        "mHdr": (PIPE_MODE == "HDR"),
        "mSrgb": OIDN_SRGB,
        "mCleanAux": OIDN_CLEAN_AUX,
        "mQuality": OIDN_QUALITY,
        "mMaxMemoryMB": OIDN_MAX_MEM_MB,
        "mInputScale": OIDN_INPUT_SCALE,  # NaN auto
    }


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
    2nd ToneMapper only for LDR writeout:
    """
    return createPass("ToneMapper", {
        "operator": ToneMapOp.Linear,
        "autoExposure": False,
        "exposureCompensation": 0.0,  
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

# ----------------------------
# Graph builder
# ----------------------------
def render_graph():
    g = RenderGraph(f"Pipe {PIPE_MODE}")

    loadRenderPassLibrary("AccumulatePass.dll")
    loadRenderPassLibrary("VolumetricReSTIR.dll")
    loadRenderPassLibrary("ToneMapper.dll")
    loadRenderPassLibrary("OIDNGPUPass.dll")

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
        Acc    = createPass("AccumulatePass", {"enableAccumulation": True, "autoReset": False})
        TM1    = make_tonemapper_primary()

        g.addPass(ReSTIR, "ReSTIR")
        g.addPass(Acc,    "Acc")
        g.addPass(TM1,    "TM1")

        g.addEdge("ReSTIR.accumulated_color", "Acc.input")
        g.addEdge("Acc.output",              "TM1.src")
        g.markOutput("TM1.dst")
        return g

    # HDR/LDR PATHS
    ReSTIR = createPass("VolumetricReSTIR", {
        "mParams": VolumetricReSTIRParams(
            mUseSurfaceScene=True,
            mUseEmissiveLights=True,
            mUseEnvironmentLights=False,
            mTemporalReuseMThreshold=10.0
        )
    })

    Acc   = createPass("AccumulatePass", {"enableAccumulation": False})
    OIDN  = createPass("OIDNGPUPass", make_oidn_params())
    TM1   = make_tonemapper_primary()

    g.addPass(ReSTIR, "ReSTIR")
    g.addPass(Acc,    "Acc")
    g.addPass(OIDN,   "OIDN")
    g.addPass(TM1,    "TM1")

    if PIPE_MODE == "HDR":
        # HDR: OIDN BEFORE ToneMapper (denoise linear HDR)
        g.addEdge("ReSTIR.accumulated_color", "Acc.input")
        g.addEdge("Acc.output",              "OIDN.src")
        g.addEdge("OIDN.dst",                "TM1.src")
        g.markOutput("TM1.dst")
    else:
        # LDR: ToneMapper first -> OIDN (mHdr=False) -> TM2 writeout
        TM2 = make_tonemapper_writeout()
        g.addPass(TM2, "TM2")

        g.addEdge("ReSTIR.accumulated_color", "Acc.input")
        g.addEdge("Acc.output",              "TM1.src")
        g.addEdge("TM1.dst",                 "OIDN.src")
        g.addEdge("OIDN.dst",                "TM2.src")
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

print("OIDN params:")
p = make_oidn_params()
for k in ["mEnabled","mHdr","mSrgb","mCleanAux","mQuality","mMaxMemoryMB","mInputScale"]:
    print(f"  {k} = {p[k]}")

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
