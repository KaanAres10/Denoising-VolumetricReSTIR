# ============================================================
# Plume: Volumetric ReSTIR / OptiX 9.0(Blend) /Reference / NoDenoiser
# Capture modes: "timing", "frames", "both"
#
# PIPE_MODE:
#   - "REF"      : ReSTIR reference accumulation -> ToneMapper (NUM_FRAMES forced to 1)
#   - "OPTIX"    : ReSTIR -> Acc -> OptiX (blend) -> ToneMapper
#   - "NODENOISE": ReSTIR -> Acc -> ToneMapper   (true baseline, OptiX not used)
# ============================================================

from falcor import *
import os

# ----------------------------
# CONFIG
# ----------------------------
PIPE_MODE    = "NODENOISE"          # "OPTIX" | "REF" | "NODENOISE"
CAPTURE_MODE = "frames"       # "timing" | "frames" | "both"
BLEND_FACTOR = 1.0            # only used for OPTIX

W, H = 1920, 1080
NUM_FRAMES = 100

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

OUT_ROOT = os.path.join(
    SCRIPT_DIR,
    "outputs",
    "Plume_Optix_Blend"
)

# Optional: skip capturing first frames 
CAPTURE_START_FRAME = 0     

# Reference quality
BASELINE_SPP = 20
ACCUM_FRAMES = 1000

# Force single output frame for reference
if PIPE_MODE == "REF":
    NUM_FRAMES = 1

# Helpers
def blend_to_str(b: float) -> str:
    return f"{b:.2f}"

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
            mBaselineSamplePerPixel=BASELINE_SPP,
        )

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


    if PIPE_MODE == "NODENOISE":
        ReSTIR = createPass("VolumetricReSTIR")
        Acc    = createPass("AccumulatePass", {"enableAccumulation": False})
        TM     = make_tonemapper()

        g.addPass(ReSTIR, "ReSTIR")
        g.addPass(Acc,    "Acc")
        g.addPass(TM,     "TM")

        g.addEdge("ReSTIR.accumulated_color", "Acc.input")
        g.addEdge("Acc.output",              "TM.src")
        g.markOutput("TM.dst")
        return g


    loadRenderPassLibrary("OptixDenoiserRecent.dll")

    ReSTIR = createPass("VolumetricReSTIR")
    Acc    = createPass("AccumulatePass", {"enableAccumulation": False})

    Denoiser = createPass("OptixDenoiserRecent", {
        "enabled": True,
        "blend": float(BLEND_FACTOR),
        "denoiseAlpha": False,
    })

    TM = make_tonemapper()

    g.addPass(ReSTIR,   "ReSTIR")
    g.addPass(Acc,      "Acc")
    g.addPass(Denoiser, "Denoiser")
    g.addPass(TM,       "TM")

    g.addEdge("ReSTIR.accumulated_color", "Acc.input")
    g.addEdge("Acc.output",              "Denoiser.color")

    g.addEdge("Denoiser.output", "TM.src")
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


if PIPE_MODE == "REF":
    out_dir = os.path.join(OUT_ROOT, "REF")
    base = "ref"
elif PIPE_MODE == "NODENOISE":
    out_dir = os.path.join(OUT_ROOT, "NoDenoiser")
    base = "NoDenoiser"
else:
    bstr = blend_to_str(BLEND_FACTOR)
    out_dir = os.path.join(OUT_ROOT, f"Optix_Blend_{bstr}")
    base = f"OptixBlend_{bstr}"

os.makedirs(out_dir, exist_ok=True)

if CAPTURE_MODE in ("timing", "both"):
    tc.captureFrameTime(os.path.join(out_dir, "frame_times.csv"))

if CAPTURE_MODE in ("frames", "both"):
    fc.outputDir = out_dir

print(f"PIPE_MODE={PIPE_MODE}")
print(f"CAPTURE_MODE={CAPTURE_MODE}")
print(f"OUT_DIR={out_dir}")
print(f"NUM_FRAMES={NUM_FRAMES}")
if PIPE_MODE == "OPTIX":
    print(f"BLEND_FACTOR={BLEND_FACTOR}")
if PIPE_MODE == "REF":
    print(f"REF: BASELINE_SPP={BASELINE_SPP}, ACCUM_FRAMES={ACCUM_FRAMES} => ~{BASELINE_SPP*ACCUM_FRAMES} spp")

# For REF accumulation
accumPass = m.activeGraph.getPass("Acc") if PIPE_MODE == "REF" else None

# MAIN LOOP
for i in range(NUM_FRAMES):
    if PIPE_MODE == "REF":
        accumPass.reset()
        for _ in range(ACCUM_FRAMES):
            renderFrame()
    else:
        renderFrame()

    if CAPTURE_MODE in ("frames", "both") and i >= CAPTURE_START_FRAME:
        fc.baseFilename = f"{base}_{i:04d}"
        fc.capture()

print("Done.")
exit()
