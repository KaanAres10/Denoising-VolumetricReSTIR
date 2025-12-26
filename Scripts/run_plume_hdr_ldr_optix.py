# ============================================================
# Plume: Volumetric ReSTIR / OptiX (HDR vs LDR) / Reference
# Capture modes: "timing", "frames", "both"
# PIPE_MODE: "HDR", "LDR", "REF"
# REF always outputs NUM_FRAMES = 1 (single accumulated frame)
# ============================================================

from falcor import *
import os

# ----------------------------
# CONFIG
# ----------------------------
PIPE_MODE    = "REF"        # "HDR" | "LDR" | "REF"
CAPTURE_MODE = "frames"     # "timing" | "frames" | "both"
USE_TEMPORAL = False        # True => connect mvec + model=4 (HDR/LDR only)

W, H = 1920, 1080
NUM_FRAMES = 100            # used for HDR/LDR; REF will override to 1 below


def find_repo_root(start):
    cur = start
    while True:
        parent = os.path.dirname(cur)
        if parent == cur:
            return start
        if os.path.isdir(os.path.join(cur, "Source")):
            return cur
        cur = parent

BIN_DIR = os.getcwd()
REPO_ROOT = find_repo_root(BIN_DIR)

OUT_ROOT = os.path.join(
    REPO_ROOT,
    "outputs",
    "Plume_Optix_HDR_LDR"
)

OUT_DIR  = os.path.join(OUT_ROOT, PIPE_MODE)  # HDR / LDR / REF
BASE     = PIPE_MODE.lower()

os.makedirs(OUT_DIR, exist_ok=True)

# Reference quality
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

def make_tonemapper():
    return createPass("ToneMapper", {
        "operator": ToneMapOp.Linear,
        "autoExposure": False,
        "exposureCompensation": 1.0,
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

def make_tonemapper_writeout():
    """
    TM2 for LDR-only
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

def render_graph():
    g = RenderGraph(f"Plume Pipe {PIPE_MODE}")

    loadRenderPassLibrary("AccumulatePass.dll")
    loadRenderPassLibrary("VolumetricReSTIR.dll")
    loadRenderPassLibrary("ToneMapper.dll")


    if PIPE_MODE == "REF":
        params = VolumetricReSTIRParams(
            mUseReference=True,
            mBaselineSamplePerPixel=BASELINE_SPP)

        ReSTIR = createPass("VolumetricReSTIR", {"mParams": params})
        Acc    = createPass("AccumulatePass", {"enableAccumulation": True, "autoReset": False})
        TM     = make_tonemapper()

        g.addPass(ReSTIR, "ReSTIR")
        g.addPass(Acc,   "Acc")
        g.addPass(TM,    "TM")

        g.addEdge("ReSTIR.accumulated_color", "Acc.input")
        g.addEdge("Acc.output",              "TM.src")
        g.markOutput("TM.dst")
        return g

    loadRenderPassLibrary("OptixDenoiserRecent.dll")

    ReSTIR = createPass("VolumetricReSTIR")

    Acc  = createPass("AccumulatePass", {"enableAccumulation": False})
    Optx = createPass("OptixDenoiserRecent", make_optix_params())
    TM1  = make_tonemapper()

    g.addPass(ReSTIR, "ReSTIR")
    g.addPass(Acc,   "Acc")
    g.addPass(Optx,  "Optix")
    g.addPass(TM1,   "TM1")

    if PIPE_MODE == "HDR":
        g.addEdge("ReSTIR.accumulated_color", "Acc.input")
        g.addEdge("Acc.output",              "Optix.color")
        if USE_TEMPORAL:
            g.addEdge("ReSTIR.mvec", "Optix.mvec")
        g.addEdge("Optix.output",            "TM1.src")
        g.markOutput("TM1.dst")
        return g

    # ----------------------------
    # LDR: TM1 -> OptiX(LDR) -> TM2(writeout) -> output
    # ----------------------------
    TM2 = make_tonemapper_writeout()
    g.addPass(TM2, "TM2")

    g.addEdge("ReSTIR.accumulated_color", "Acc.input")
    g.addEdge("Acc.output",              "TM1.src")
    g.addEdge("TM1.dst",                 "Optix.color")
    if USE_TEMPORAL:
        g.addEdge("ReSTIR.mvec", "Optix.mvec")

    g.addEdge("Optix.output",            "TM2.src")
    g.markOutput("TM2.dst")
    return g


m.loadScene("default.obj")
m.scene.setEnvMap("hansaplatz_8k.hdr")

m.addGVDBVolume(
    sigma_a=float3(6,6,6),
    sigma_s=float3(14,14,14),
    g=0.0,
    dataFile="fire115/fire115.0198",
    numMips=4,
    densityScale=0.1,
    hasVelocity=False,
    hasEmission=False,
    LeScale=0.01,
    temperatureCutoff=900.0,
    temperatureScale=0.0,
    worldTranslation=float3(0,1.686,0),
    worldRotation=float3(0,0,0),
    worldScaling=0.013
)

m.scene.animated = False
m.scene.camera.animated = False
m.scene.cameraSpeed = 1

m.scene.camera.position = float3(1.977354, 2.411630, 2.242076)
m.scene.camera.target   = float3(1.366226, 2.220231, 1.474033)
m.scene.camera.up       = float3(0.000000, 1.000000, 0.000000)


graph = render_graph()
m.addGraph(graph)

m.resizeSwapChain(W, H)

m.ui = False
fc.ui = False

t.time = 0
t.framerate = 0


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
