# ReSTIR against brute-force path tracing at ONE still pose: bistro, orbit pose 150 of time_raw.py (the
# verify frame), the same scene, estimator settings and camera as that script and as the legacy twin
# outputs/legacy_cmp/_reference_pose_legacy.py (the falcor4-legacy build), so the two engines' ReSTIR can
# each be scored against a path-traced reference of the same image.
#
#   VR_MODE=reference|restir   brute-force volumetric path tracing (mUseReference, no reuse), or ReSTIR
#   VR_FRAMES=2048             frames rendered at the pose; the camera never moves
#   VR_SPP=16                  reference samples per pixel per frame (mBaselineSamplePerPixel)
#   VR_CAPTURES=8              captures at FRAMES*k/CAPTURES, k = 1..CAPTURES: AccumulatePass.output (the
#                              running average since frame 0) and, for ReSTIR, the raw frame itself
#   VR_OUT_DIR, VR_TAG         where, and the file prefix
#   VR_NO_TEMPORAL / VR_NO_SPATIAL   as time_raw.py
#
# Captures are HDR (.exr). Two averages A(n) at n = FRAMES/2 and FRAMES give the second half's mean,
# 2 A(FRAMES) - A(FRAMES/2), which leaves out the frames where temporal reuse is still filling its history,
# and two independent halves for estimating the average's own noise.
import math
import os
import sys

_HERE = r"C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts"
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    pass
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from falcor import *
import vr_graph as vr

vr.bind(m)

W, H = 1920, 1080
MODE = vr.env("VR_MODE", "restir").lower()
REFERENCE = MODE == "reference"
FRAMES = vr.env_int("VR_FRAMES", 2048)
SPP = vr.env_int("VR_SPP", 16)
CAPTURES = vr.env_int("VR_CAPTURES", 8)
OUT_DIR = os.environ["VR_OUT_DIR"]
TAG = vr.env("VR_TAG", MODE)
ORBIT_FRAMES = 300  # time_raw.py's orbit length: pose 150 is the verify frame
CENTER = (-11.0, 6.025879, 0.0)

scene = vr.load_bistro()
m.scene.animated = False
m.scene.camera.animated = False

g = RenderGraph("reference_pose")
params = {"mInitialLightSamples": 1, "mFinalLightSamples": 1,
          "mEnableTemporalReuse": not REFERENCE and not vr.env_bool("VR_NO_TEMPORAL", False),
          "mEnableSpatialReuse": not REFERENCE and not vr.env_bool("VR_NO_SPATIAL", False)}
if REFERENCE:
    params.update({"mBaselineSamplePerPixel": SPP})
restir = vr.add_restir(g, scene, render=(W, H), reference=REFERENCE, mParams=params)
g.addPass(createPass("AccumulatePass", {"enabled": True}), "Accum")
g.addEdge(restir + ".accumulated_color", "Accum.input")
g.markOutput("Accum.output")
if not REFERENCE:
    g.markOutput(restir + ".accumulated_color")
m.addGraph(g)
m.resizeSwapChain(W, H)
m.ui = False
vr.pin_clock(30)

cam = m.scene.camera
cx, cy, cz = CENTER
p = cam.position
radius = math.sqrt((p.x - cx) ** 2 + (p.z - cz) ** 2)
a = math.atan2(p.z - cz, p.x - cx) + (150 / float(ORBIT_FRAMES - 1)) * (-math.pi)
cam.position = float3(cx + radius * math.cos(a), p.y, cz + radius * math.sin(a))
cam.target = float3(cx, cy, cz)

print("[reference_pose] mode=%s frames=%d spp=%d captures=%d" % (MODE, FRAMES, SPP, CAPTURES))
m.renderFrame()  # frame 0: camera settles, the accumulation starts here
f0 = int(m.clock.frame)
frames = [f0 + FRAMES * k // CAPTURES - 1 for k in range(1, CAPTURES + 1)]
os.makedirs(OUT_DIR, exist_ok=True)
m.frameCapture.outputDir = OUT_DIR
m.frameCapture.baseFilename = TAG
m.frameCapture.addFrames(g, frames)
with open(os.path.join(OUT_DIR, TAG + ".frames.txt"), "w") as fh:
    fh.write("first %d\n" % f0 + "".join("%d %d\n" % (fr, fr - f0 + 1) for fr in frames))
m.clock.exitFrame = frames[-1] + 60
for _ in range(FRAMES + 64):
    m.renderFrame()
