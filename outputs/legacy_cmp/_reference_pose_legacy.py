# Tracked copy of legacy/Scripts/_reference_pose_legacy.py (untracked in the falcor4-legacy worktree). Run it
# from there with the legacy Mogwai; outputs/pending_9p/forkref/run.sh does.
# Falcor 4 fork twin of Source/RenderPasses/VolumetricReSTIR/Scripts/reference_pose.py: ReSTIR, or
# brute-force path tracing, at orbit pose 150 of _time_raw_legacy.py (the verify frame), camera still,
# averaged by AccumulatePass. Same scene, estimator settings and camera as _time_raw_legacy.py.
#   VR_MODE=reference|restir  VR_FRAMES=2048  VR_SPP=16  VR_CAPTURES=8  VR_OUT_DIR  VR_TAG
#   VR_NO_TEMPORAL / VR_NO_SPATIAL
# Captures at FRAMES*k/CAPTURES: Accum.output (running average) and, for ReSTIR, the raw frame. The clock
# is paused (frame 0), so each capture gets its own file prefix, <TAG>_<k>.
from falcor import *
import math, os, sys

W, H = 1920, 1080
MODE = os.environ.get("VR_MODE", "restir").lower()
REFERENCE = MODE == "reference"
FRAMES = int(os.environ.get("VR_FRAMES", "2048"))
SPP = int(os.environ.get("VR_SPP", "16"))
CAPTURES = int(os.environ.get("VR_CAPTURES", "8"))
OUT_DIR = os.environ["VR_OUT_DIR"]
TAG = os.environ.get("VR_TAG", MODE)
ORBIT_FRAMES = 300
D = "C:/research/Denoising-VolumetricReSTIR/VolumetricReSTIRData"
CENTER = (-11.0, 6.025879, 0.0)

def render_graph():
    g = RenderGraph("reference_pose_legacy")
    loadRenderPassLibrary("VolumetricReSTIR.dll")
    loadRenderPassLibrary("AccumulatePass.dll")
    vrestir = createPass("VolumetricReSTIR", {
        "mParams": VolumetricReSTIRParams(
            mUseSurfaceScene=True, mUseEmissiveLights=True,
            mUseEnvironmentLights=False, mTemporalReuseMThreshold=10.0,
            mInitialLightSamples=1, mFinalLightSamples=1,
            mUseReference=REFERENCE, mBaselineSamplePerPixel=SPP,
            mEnableSpatialReuse=not REFERENCE and not os.environ.get("VR_NO_SPATIAL"),
            mEnableTemporalReuse=not REFERENCE and not os.environ.get("VR_NO_TEMPORAL"))})
    accum = createPass("AccumulatePass", {"enableAccumulation": True})
    g.addPass(vrestir, "VolumetricReSTIR")
    g.addPass(accum, "Accum")
    g.addEdge("VolumetricReSTIR.accumulated_color", "Accum.input")
    g.markOutput("Accum.output")
    if not REFERENCE:
        g.markOutput("VolumetricReSTIR.accumulated_color")
    return g

m.loadScene(D + "/Bistro_5_1/BistroExterior.fbx")
m.scene.setEnvMap(D + "/skylight-morn.exr")
m.scene.setEnvMapRotation(float3(0, 72.5, 0))
m.scene.setEnvMapIntensity(0)
m.addGVDBVolume(sigma_a=float3(10,10,10), sigma_s=float3(80,80,80), g=0.0,
                dataFile=D + "/smoke-plume-2", numMips=4)
m.scene.animated = False
m.scene.camera.animated = False
m.scene.camera.position = float3(-15.149291, 8.352362, -8.399609)
m.scene.camera.target   = float3(-14.742913, 8.025879, -7.546224)
m.scene.camera.up       = float3(0.004061, 0.999961, 0.007782)

m.addGraph(render_graph())
m.resizeSwapChain(W, H)
m.ui = False
fc.ui = False
t.pause(); t.frame = 0; t.framerate = 30

# Falcor 4's float3 binding does not expose .x/.y/.z to Python (see _time_raw_legacy.py).
import re
_f = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
def f3(v):
    n = _f.findall(str(v))
    return float(n[0]), float(n[1]), float(n[2])
cx, cy, cz = CENTER
sx, sy, sz = f3(m.scene.camera.position)
radius = math.sqrt((sx - cx) ** 2 + (sz - cz) ** 2)
a = math.atan2(sz - cz, sx - cx) + (150 / float(ORBIT_FRAMES - 1)) * (-math.pi)
m.scene.camera.position = float3(cx + radius * math.cos(a), sy, cz + radius * math.sin(a))
m.scene.camera.target = float3(cx, cy, cz)

print("[reference_pose_legacy] mode=%s frames=%d spp=%d captures=%d" % (MODE, FRAMES, SPP, CAPTURES))
sys.stdout.flush()
fc.outputDir = OUT_DIR
at = {FRAMES * k // CAPTURES: k for k in range(1, CAPTURES + 1)}
for n in range(1, FRAMES + 1):
    renderFrame()
    if n in at:
        fc.baseFilename = "%s_%02d" % (TAG, at[n])
        fc.capture()
for _ in range(8):
    renderFrame()
print("[reference_pose_legacy] done")
sys.stdout.flush()
exit()
