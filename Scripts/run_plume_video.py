from falcor import *
import math, re, os, time

# ============================================================
# CONFIG
# ============================================================
W, H = 1920, 1080
FPS = 30
FRAMES = 300                 
ORBIT_DEGREES = 180.0

# Choose: "timing", "frames", "both"
MODE = "frames"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

OUT_ROOT = os.path.join(
    SCRIPT_DIR,
    "outputs",
    "Plume_Video"
)


OUT_DIR = OUT_ROOT
os.makedirs(OUT_DIR, exist_ok=True)

CENTER = float3(0.0, 1.686, 0.0)

stamp = time.strftime("%Y%m%d_%H%M%S")
BASE_NAME = f"FireOrbit_{stamp}"

# Helpers
_float_re = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")

def f3_to_xyz(v):
    nums = _float_re.findall(str(v))
    if len(nums) < 3:
        raise ValueError(f"Could not parse float3 from: {v}")
    return float(nums[0]), float(nums[1]), float(nums[2])


def render_graph():
    g = RenderGraph("VolumetricReSTIR_Orbit")

    loadRenderPassLibrary("VolumetricReSTIR.dll")
    loadRenderPassLibrary("AccumulatePass.dll")
    loadRenderPassLibrary("ToneMapper.dll")

    vrestir = createPass("VolumetricReSTIR")
    accum   = createPass("AccumulatePass", {"enableAccumulation": False})
    tonemap = createPass("ToneMapper", {
        "operator": ToneMapOp.Linear,
        "autoExposure": True,
        "exposureCompensation": 2.0,
        "clamp": True,
    })

    g.addPass(vrestir, "VolumetricReSTIR")
    g.addPass(accum,   "AccumulatePass")
    g.addPass(tonemap, "ToneMapper")

    g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
    g.addEdge("AccumulatePass.output", "ToneMapper.src")

    g.markOutput("ToneMapper.dst")
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
    worldTranslation=CENTER,
    worldRotation=float3(0,0,0),
    worldScaling=0.013
)

m.scene.animated = False
m.scene.camera.animated = False


m.scene.camera.position = float3(1.977354, 2.411630, 2.242076)
m.scene.camera.target   = float3(1.366226, 2.220231, 1.474033)
m.scene.camera.up       = float3(0.0, 1.0, 0.0)


m.addGraph(render_graph())
resizeSwapChain(W, H)
m.ui = False
fc.ui = False


if MODE in ("timing", "both"):
    tc.captureFrameTime(os.path.join(OUT_DIR, "frame_times.csv"))


t.pause()
t.frame = 0
t.framerate = FPS

# Orbit parameters
cx, cy, cz = f3_to_xyz(CENTER)
sx, sy, sz = f3_to_xyz(m.scene.camera.position)

radius = math.sqrt((sx - cx)**2 + (sz - cz)**2)
height = sy - cy
startAngle = math.atan2(sz - cz, sx - cx)
orbitRadians = ORBIT_DEGREES * math.pi / 180.0


if MODE in ("frames", "both"):
    fc.outputDir = OUT_DIR

print(f"MODE = {MODE}")
print(f"OUT_DIR = {OUT_DIR}")
print(f"Frames = {FRAMES} @ {FPS}fps")

# Main loop
for i in range(FRAMES):
    u = i / float(FRAMES - 1)
    ang = startAngle + u * orbitRadians

    px = cx + radius * math.cos(ang)
    pz = cz + radius * math.sin(ang)
    py = cy + height

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
