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
    "Bistro_Reference_Video"
)
OUT_DIR = OUT_ROOT
os.makedirs(OUT_DIR, exist_ok=True)

ORBIT_FRAMES  = 300
ORBIT_DEGREES = -180.0  

# Reference quality
BASELINE_SPP = 30
ACCUM_FRAMES = 500

stamp = time.strftime("%Y%m%d_%H%M%S")
BASE_NAME = f"Bistro_REF_{stamp}"

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


def render_graph():
    g = RenderGraph("Bistro_VolumetricReSTIR_ReferenceOrbit")

    loadRenderPassLibrary("AccumulatePass.dll")
    loadRenderPassLibrary("VolumetricReSTIR.dll")
    loadRenderPassLibrary("ToneMapper.dll")

    params = VolumetricReSTIRParams(
        mUseReference=True,
        mBaselineSamplePerPixel=BASELINE_SPP,

        mEnableTemporalReuse=False,
        mEnableSpatialReuse=False,
        mVertexReuse=False,

        mUseSurfaceScene=True,
        mUseEmissiveLights=True,
        mUseEnvironmentLights=False,
        mTemporalReuseMThreshold=10.0,
    )

    vrestir = createPass("VolumetricReSTIR", {"mParams": params})

    accum = createPass("AccumulatePass", {
        "enableAccumulation": True,
        "autoReset": False,
    })

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

    g.addPass(vrestir, "VolumetricReSTIR")
    g.addPass(accum,  "AccumulatePass")
    g.addPass(tonemap,"ToneMapper")

    g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
    g.addEdge("AccumulatePass.output", "ToneMapper.src")

    g.markOutput("ToneMapper.dst")
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

m.scene.camera.position = float3(-15.149291, 8.352362, -8.399609)
m.scene.camera.target   = float3(-14.742913, 8.025879, -7.546224)
m.scene.camera.up       = float3(0.004061, 0.999961, 0.007782)


g = render_graph()
m.addGraph(g)

m.resizeSwapChain(W, H)
m.ui = False
fc.ui = False


cx, cy, cz = f3_to_xyz(ORBIT_CENTER)
sx, sy, sz = f3_to_xyz(m.scene.camera.position)

y_offset = sy - cy

base_radius = math.sqrt((sx - cx)**2 + (sz - cz)**2)
radius = base_radius * RADIUS_SCALE + RADIUS_ADD

startAngle = math.atan2(sz - cz, sx - cx)
orbitRadians = ORBIT_DEGREES * math.pi / 180.0


fc.outputDir = OUT_DIR
t.pause()

accumPass = m.activeGraph.getPass("AccumulatePass")

print(f"OUT_DIR: {OUT_DIR}")
print(f"ORBIT_FRAMES={ORBIT_FRAMES}, ORBIT_DEGREES={ORBIT_DEGREES}")
print(f"ORBIT_CENTER=({cx:.3f},{cy:.3f},{cz:.3f})")
print(f"base_radius={base_radius:.3f}  radius={radius:.3f}  y_offset={y_offset:.3f}")
print(f"BASELINE_SPP={BASELINE_SPP}, ACCUM_FRAMES={ACCUM_FRAMES}  => effective ~{BASELINE_SPP * ACCUM_FRAMES} spp/frame")

# Main loop 
for frame_id in range(ORBIT_FRAMES):
    u = frame_id / float(ORBIT_FRAMES - 1)
    ang = startAngle + u * orbitRadians

    px = cx + radius * math.cos(ang)
    pz = cz + radius * math.sin(ang)
    py = cy + y_offset

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
