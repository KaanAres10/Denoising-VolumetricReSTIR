# ============================================================
# Bistro: Volumetric ReSTIR/OptiX 9.0(Blend) / Reference / NoDenoiser
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
PIPE_MODE    = "NODENOISE"     # "OPTIX" | "REF" | "NODENOISE"
CAPTURE_MODE = "frames"    # "timing" | "frames" | "both"
BLEND_FACTOR = 1.0         # only used for OPTIX

W, H = 1920, 1080
NUM_FRAMES = 100

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

OUT_ROOT = os.path.join(
    SCRIPT_DIR,
    "outputs",
    "Bistro_Optix_Blend"
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


def render_graph():
    g = RenderGraph(f"Bistro {PIPE_MODE}")

    loadRenderPassLibrary("AccumulatePass.dll")
    loadRenderPassLibrary("VolumetricReSTIR.dll")
    loadRenderPassLibrary("ToneMapper.dll")


    if PIPE_MODE == "REF":
        params = VolumetricReSTIRParams(
            mUseSurfaceScene=True,
            mUseEmissiveLights=True,
            mUseEnvironmentLights=False,
            mTemporalReuseMThreshold=10.0,

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
        params = VolumetricReSTIRParams(
            mUseSurfaceScene=True,
            mUseEmissiveLights=True,
            mUseEnvironmentLights=False,
            mTemporalReuseMThreshold=10.0,
        )

        ReSTIR = createPass("VolumetricReSTIR", {"mParams": params})
        Acc    = createPass("AccumulatePass", {"enableAccumulation": False})
        TM     = make_tonemapper()

        g.addPass(ReSTIR, "ReSTIR")
        g.addPass(Acc,    "Acc")
        g.addPass(TM,     "TM")

        g.addEdge("ReSTIR.accumulated_color", "Acc.input")
        g.addEdge("Acc.output",              "TM.src")
        g.markOutput("TM.dst")
        return g

    # OPTIX PATH (single blend factor)
    loadRenderPassLibrary("OptixDenoiserRecent.dll")

    params = VolumetricReSTIRParams(
        mUseSurfaceScene=True,
        mUseEmissiveLights=True,
        mUseEnvironmentLights=False,
        mTemporalReuseMThreshold=10.0,
    )

    ReSTIR = createPass("VolumetricReSTIR", {"mParams": params})
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

m.loadScene("Bistro_5_1/BistroExterior.fbx")
m.scene.setEnvMap("skylight-morn.exr")
m.scene.setEnvMapRotation(float3(0,72.5,0))
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
m.scene.camera.position = float3(-15.149291,8.352362,-8.399609)
m.scene.camera.target   = float3(-14.742913,8.025879,-7.546224)
m.scene.camera.up       = float3(0.004061,0.999961,0.007782)
m.scene.cameraSpeed     = 1.0


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
