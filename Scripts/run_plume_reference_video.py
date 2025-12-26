from falcor import *
import math, os, time, re

# ============================================================
# CONFIG
# ============================================================
W, H = 1920, 1080

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
    "Plume_Reference_Video"
)

OUT_DIR = OUT_ROOT
os.makedirs(OUT_DIR, exist_ok=True)

ORBIT_FRAMES  = 300
ORBIT_DEGREES = 180.0

# Reference rendering quality 
BASELINE_SPP = 30
ACCUM_FRAMES = 500    

CENTER = float3(0.0, 1.686, 0.0)

stamp = time.strftime("%Y%m%d_%H%M%S")
BASE_NAME = f"ref_orbit_{stamp}"


def render_graph():
    g = RenderGraph("VolumetricReSTIR_ReferenceOrbit")

    loadRenderPassLibrary("AccumulatePass.dll")
    loadRenderPassLibrary("VolumetricReSTIR.dll")
    loadRenderPassLibrary("ToneMapper.dll")

    params = VolumetricReSTIRParams(
        mUseReference=True,
        mBaselineSamplePerPixel=BASELINE_SPP,

        mEnableTemporalReuse=False,
        mEnableSpatialReuse=False,
        mVertexReuse=False,

        mUseEnvironmentLights=True,
        mUseAnalyticLights=False,
        mUseEmissiveLights=False,
    )

    vrestir = createPass("VolumetricReSTIR", {"mParams": params})

    accum = createPass("AccumulatePass", {
        "enableAccumulation": True,
        "autoReset": False,     
    })

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

# Helpers
_float_re = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")

def f3_to_xyz(v):
    s = str(v)
    nums = _float_re.findall(s)
    if len(nums) < 3:
        raise ValueError(f"Could not parse float3 from: {s}")
    return float(nums[0]), float(nums[1]), float(nums[2])


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

g = render_graph()
m.addGraph(g)

resizeSwapChain(W, H)
m.ui = False
fc.ui = False

# Orbit setup
cx, cy, cz = f3_to_xyz(CENTER)
sx, sy, sz = f3_to_xyz(m.scene.camera.position)

ox = sx - cx
oy = sy - cy
oz = sz - cz

radius = math.sqrt(ox*ox + oz*oz)
height = oy
startAngle = math.atan2(oz, ox)
orbitRadians = ORBIT_DEGREES * (math.pi / 180.0)


fc.outputDir = OUT_DIR

t.pause() 

accumPass = m.activeGraph.getPass("AccumulatePass")

print(f"OUT_DIR: {OUT_DIR}")
print(f"ORBIT_FRAMES={ORBIT_FRAMES}, BASELINE_SPP={BASELINE_SPP}, ACCUM_FRAMES={ACCUM_FRAMES}")

# Main loop
for frame_id in range(ORBIT_FRAMES):
    u = frame_id / float(ORBIT_FRAMES - 1)
    ang = startAngle + u * orbitRadians

    px = cx + radius * math.cos(ang)
    pz = cz + radius * math.sin(ang)
    py = cy + height

    m.scene.camera.position = float3(px, py, pz)
    m.scene.camera.target   = float3(cx, cy, cz)

    accumPass.reset()

    for _ in range(ACCUM_FRAMES):
        renderFrame()

    fc.baseFilename = f"{BASE_NAME}_{frame_id:04d}"
    fc.capture()

    if frame_id % 10 == 0:
        print(f"Captured {frame_id}/{ORBIT_FRAMES-1}")

print("Done.")
exit()
