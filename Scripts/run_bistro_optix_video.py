# Graphs
from falcor import *
import math, os, time, re


W, H = 1920, 1080
FPS = 30
FRAMES = 300
ORBIT_DEGREES = -180.0

# Choose: "timing", "frames", "both"
MODE = "frames"

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
    "Bistro_Optix_Video"
)
OUT_DIR = OUT_ROOT

os.makedirs(OUT_ROOT, exist_ok=True)

stamp = time.strftime("%Y%m%d_%H%M%S")
BASE_NAME = f"Bistro_OptixOrbit_{stamp}"

# Orbit controls
ORBIT_CENTER = float3(-11.0, 6.025879, 0.0)
RADIUS_SCALE = 1.0
RADIUS_ADD   = 0.0

# Helpers
_float_re = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
def f3_to_xyz(v):
    nums = _float_re.findall(str(v))
    if len(nums) < 3:
        raise ValueError(f"Could not parse float3 from: {v}")
    return float(nums[0]), float(nums[1]), float(nums[2])


gAccumulateParams = {"enableAccumulation": False}
gDenoiserParams = {
    "enabled": True,
    "blend": 0.0,
    "denoiseAlpha": False
}

def render_graph():
    g = RenderGraph("Bistro VolumetricReSTIR + OptiX Orbit")

    loadRenderPassLibrary("AccumulatePass.dll")
    loadRenderPassLibrary("VolumetricReSTIR.dll")
    loadRenderPassLibrary("OptixDenoiserRecent.dll")
    loadRenderPassLibrary("ToneMapper.dll")

    vrestir = createPass(
        "VolumetricReSTIR",
        {
            "mParams": VolumetricReSTIRParams(
                mUseSurfaceScene=True,
                mUseEmissiveLights=True,
                mUseEnvironmentLights=False,
                mTemporalReuseMThreshold=10.0
            )
        }
    )

    accum    = createPass("AccumulatePass", gAccumulateParams)
    denoiser = createPass("OptixDenoiserRecent", gDenoiserParams)

    tonemap = createPass("ToneMapper", {
        "operator": ToneMapOp.Linear,
        "autoExposure": True,
        "exposureCompensation": 0.0,
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

    g.addPass(vrestir,  "VolumetricReSTIR")
    g.addPass(accum,    "AccumulatePass")
    g.addPass(denoiser, "DenoiserPass")
    g.addPass(tonemap,  "ToneMapper")

    g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
    g.addEdge("AccumulatePass.output", "DenoiserPass.color")
    g.addEdge("DenoiserPass.output", "ToneMapper.src")

    g.markOutput("ToneMapper.dst")
    return g


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
m.scene.cameraSpeed = 1.0


graph = render_graph()
m.addGraph(graph)

m.resizeSwapChain(W, H)
m.ui = False
fc.ui = False
vc.ui = False

t.pause()
t.frame = 0
t.framerate = FPS

# Capture toggles
if MODE in ("timing", "both"):
    tc.captureFrameTime(os.path.join(OUT_ROOT, "frame_times.csv"))
if MODE in ("frames", "both"):
    fc.outputDir = OUT_ROOT
# ============================================================
# Orbit setup (same math as your current working orbit script)
# ============================================================
cx, cy, cz = f3_to_xyz(ORBIT_CENTER)
sx, sy, sz = f3_to_xyz(m.scene.camera.position)

y_offset = sy - cy

base_radius = math.sqrt((sx - cx)**2 + (sz - cz)**2)
radius = base_radius * RADIUS_SCALE + RADIUS_ADD

startAngle = math.atan2(sz - cz, sx - cx)
orbitRadians = ORBIT_DEGREES * math.pi / 180.0

print(f"MODE={MODE}")
print(f"OUT_DIR={OUT_DIR}")
print(f"ORBIT_CENTER=({cx:.3f},{cy:.3f},{cz:.3f})")
print(f"base_radius={base_radius:.3f}  radius={radius:.3f}  y_offset={y_offset:.3f}")

# ============================================================
# Main loop
# ============================================================
for i in range(FRAMES):
    u = i / float(FRAMES - 1)
    ang = startAngle + u * orbitRadians

    px = cx + radius * math.cos(ang)
    pz = cz + radius * math.sin(ang)
    py = cy + y_offset

    m.scene.camera.position = float3(px, py, pz)
    m.scene.camera.target   = float3(cx, cy, cz)

    renderFrame()

    if MODE in ("frames", "both"):
        fc.baseFilename = f"{BASE_NAME}_{i:04d}"
        fc.capture()

    if i % 25 == 0:
        print(f"Frame {i}/{FRAMES-1}")

print("Done.")
exit()
