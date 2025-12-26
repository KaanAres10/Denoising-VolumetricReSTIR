from falcor import *
import os
import math

# CONFIG
PIPE_MODE    = "REF"      # "OIDN" | "REF"
CAPTURE_MODE = "frames"    # "timing" | "frames" | "both"

# Pick ONE quality mode here:
OIDN_MODE = "High"         # "Fast" | "Balanced" | "High"

W, H = 1920, 1080
NUM_FRAMES = 100

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
    "Plume_OIDN_Quality"
)


# folder naming
OUT_DIR = os.path.join(OUT_ROOT, f"{OIDN_MODE}" if PIPE_MODE == "OIDN" else "REF")
BASE    = "ref" if PIPE_MODE == "REF" else f"oidn_{OIDN_MODE.lower()}"

os.makedirs(OUT_DIR, exist_ok=True)

# Reference quality
BASELINE_SPP = 20
ACCUM_FRAMES = 1000
if PIPE_MODE == "REF":
    NUM_FRAMES = 1

OIDN_QUALITY_MAP = {

    "Fast":     1,
    "Balanced": 2,
    "High":     3,
}

if OIDN_MODE not in OIDN_QUALITY_MAP:
    raise RuntimeError(f"OIDN_MODE must be one of {list(OIDN_QUALITY_MAP.keys())}, got '{OIDN_MODE}'")

def make_oidn_params():
    return {
        "mEnabled": True,
        "mHdr": True,               
        "mSrgb": False,
        "mCleanAux": False,
        "mQuality": OIDN_QUALITY_MAP[OIDN_MODE],
        "mMaxMemoryMB": -1,
        "mInputScale": float("nan"),
    }

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

def render_graph():
    g = RenderGraph(f"Plume {PIPE_MODE}")

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
        g.addPass(Acc,    "Acc")
        g.addPass(TM,     "TM")

        g.addEdge("ReSTIR.accumulated_color", "Acc.input")
        g.addEdge("Acc.output",              "TM.src")
        g.markOutput("TM.dst")
        return g

    loadRenderPassLibrary("OIDNGPUPass.dll")

    ReSTIR = createPass("VolumetricReSTIR")

    Acc  = createPass("AccumulatePass", {"enableAccumulation": False})
    OIDN = createPass("OIDNGPUPass", make_oidn_params())
    TM   = make_tonemapper()

    g.addPass(ReSTIR, "ReSTIR")
    g.addPass(Acc,    "Acc")
    g.addPass(OIDN,   "OIDN")
    g.addPass(TM,     "TM")

    # HDR-only pipeline: ReSTIR -> Acc -> OIDN(HDR) -> TM -> output
    g.addEdge("ReSTIR.accumulated_color", "Acc.input")
    g.addEdge("Acc.output",              "OIDN.src")
    g.addEdge("OIDN.dst",                "TM.src")
    g.markOutput("TM.dst")

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

print(f"PIPE_MODE={PIPE_MODE} OUT_DIR={OUT_DIR} NUM_FRAMES={NUM_FRAMES}")
if PIPE_MODE == "OIDN":
    print("OIDN params:", make_oidn_params())
if PIPE_MODE == "REF":
    print(f"REF spp={BASELINE_SPP} accum={ACCUM_FRAMES} => ~{BASELINE_SPP*ACCUM_FRAMES} spp")

accumPass = m.activeGraph.getPass("Acc") if PIPE_MODE == "REF" else None

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
