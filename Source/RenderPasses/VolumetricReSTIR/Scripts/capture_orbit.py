# Capture the authored orbit as a frame sequence, for video.
#
# Same camera path as every measurement in Source/RenderPasses/NRDPass/STATE.md and as the published
# page: a -180 degree sweep about (-11, 6.025879, 0) at constant height, always looking at that point.
# The centre is NOT the camera's target -- Bistro's target sits 0.95 units from the camera, so orbiting
# around it spins the camera on the spot, which disoccludes violently and scores every denoiser ~4x
# worse. That was a property of the path, not of rotation.
#
# TIMING IS PINNED, which is the part that makes this reproducible. Without it Falcor drives `time`
# from real elapsed seconds, so the scene state at "frame 200" depends on how fast the machine ran --
# how a Bistro capture once ended up pointing at the night sky in one run and the street in another.
# vr.pin_clock(FPS) makes time = frame / framerate, so frame N is the same state on every run, on every
# machine, and at every resolution. Encode the result at the same FPS and the video is correct in wall
# time as well.
#
#   VR_SCENE=bistro|plume     VR_DISPLAY=1920x1080    VR_FRAMES=300    VR_FRAMERATE=30
#   VR_WARM=30                frames rendered at the start pose before capturing, so the temporal
#                             denoisers are converged when frame 0 is written. Without it the first
#                             seconds of every clip are a different algorithm than the rest.
#   VR_ORBIT_DEG=-180         VR_OUT_DIR=<where to write>   VR_TAG=<filename prefix>
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

RENDER = vr.env_size("VR_DISPLAY", (1920, 1080))
FRAMES = vr.env_int("VR_FRAMES", 300)
FPS = vr.env_int("VR_FRAMERATE", 30)
WARM = vr.env_int("VR_WARM", 30)
ORBIT_DEGREES = vr.env_float("VR_ORBIT_DEG", -180.0)
ORBIT_CENTER = (-11.0, 6.025879, 0.0)
OUT_DIR = os.environ["VR_OUT_DIR"]
TAG = vr.env("VR_TAG", "orbit")
SCENE = vr.env("VR_SCENE", "bistro").lower()
MODE = vr.env("VR_DENOISER", "nrd").lower()

g = RenderGraph(SCENE + "_orbit")
scene = vr.load_scene(SCENE)
restir = vr.add_restir(g, scene, render=RENDER, guides=True, mOutputDepth=True,
                       mMotionVecMode="Deterministic")
# Build the G-buffer up front and hand it to the denoiser, rather than letting each mode decide.
# add_denoiser only creates one when it is not given (`gbuffer or add_gbuffer(...)`), and the
# single-pass denoisers -- OIDN especially -- create none at all, so wiring TAA's motion vectors to
# GBufferRaster afterwards died with "Can't find render pass 'GBufferRaster'". Doing it here means
# every mode gets the same G-buffer at the same size, and none of them gets two.
#
# jitter=False matches every measurement in this project: NRD does not upscale, and NRDPass was
# passing cameraJitter in UV where NRD wants pixels until recently, so no jitter measurement here is
# trustworthy yet.
gbuf = vr.add_gbuffer(g, RENDER, jitter=False)
out = vr.add_denoiser(g, MODE, restir + ".accumulated_color", scene, RENDER, RENDER,
                      restir=restir, gbuffer=gbuf, guides=True)
tm = vr.add_tonemapper(g, out, exposure=scene.get("exposure", 0.0))
if vr.env_bool("VR_TAA_LDR", True):
    g.addPass(createPass("TAA", vr.taa_props()), "TAA_LDR")
    g.addEdge(tm, "TAA_LDR.colorIn")
    g.addEdge(gbuf + ".mvec", "TAA_LDR.motionVecs")
    tm = "TAA_LDR.colorOut"

# Only the shipped image is marked. Marking the raw HDR buffers as well means the capture can pick one
# of them, and bistro is a night exterior needing the tonemapper's +8 EV -- an HDR buffer written
# straight out looks black with a few coloured bulbs, which reads as a broken render and is not one.
g.markOutput(tm)
m.addGraph(g)
m.resizeSwapChain(RENDER[0], RENDER[1])
m.ui = False

vr.pin_clock(FPS)

cam = m.scene.camera
_cx, _cy, _cz = ORBIT_CENTER
_p = cam.position
_radius = math.sqrt((_p.x - _cx) ** 2 + (_p.z - _cz) ** 2)
_y = _p.y
_a0 = math.atan2(_p.z - _cz, _p.x - _cx)
_step = (ORBIT_DEGREES * math.pi / 180.0) / max(1, FRAMES - 1)


def place(i):
    a = _a0 + _step * i
    cam.position = float3(_cx + _radius * math.cos(a), _y, _cz + _radius * math.sin(a))
    cam.target = float3(_cx, _cy, _cz)


os.makedirs(OUT_DIR, exist_ok=True)

# VR_TIME=1 measures frame cost and captures NOTHING.
#
# These two cannot share a run. Every captured frame here is a ~2.5 MB 1080p PNG read back from the
# GPU and written asynchronously; the readback stalls the pipeline and the writes back up, so an FPS
# measured while capturing is the disk's number, not the renderer's. Hence two passes, the same split
# the reference orbit script makes with MODE = timing | frames | both -- and "both" is the one that
# quietly produces a wrong answer.
#
# What this measures is WALL CLOCK END TO END: CPU submit + GPU + present, an upper bound rather than
# a GPU-only figure. Mogwai exposes no device to Python, so Falcor's GPU profiler is unreachable from
# a script. It is directly comparable BETWEEN the configurations below, since they run the identical
# path at the identical resolution, which is what a denoiser comparison needs.
TIMING = vr.env_bool("VR_TIME", False)
if not TIMING:
    m.frameCapture.outputDir = OUT_DIR
    m.frameCapture.baseFilename = TAG
    # Frame indices are absolute, so the captured range starts after the warm-up.
    m.frameCapture.addFrames(g, [WARM + k for k in range(FRAMES)])

print("[orbit] scene=%s denoiser=%s method=%s  %dx%d  %d frames @ %d fps  warm=%d"
      % (SCENE, MODE, vr.env("VR_NRD_METHOD", "RelaxDiffuseSh"),
         RENDER[0], RENDER[1], FRAMES, FPS, WARM))
print("[orbit] r=%.3f about (%.2f,%.2f,%.2f), %.4f rad/frame -> %s"
      % (_radius, _cx, _cy, _cz, _step, OUT_DIR))
sys.stdout.flush()

# Warm-up at the START pose, so the temporal denoisers are converged before frame 0 is written.
place(0)
for _ in range(WARM):
    m.renderFrame()

import time

times = []
for i in range(FRAMES):
    place(i)
    t0 = time.perf_counter()
    m.renderFrame()
    times.append((time.perf_counter() - t0) * 1000.0)
    if i % 50 == 0:
        print("[orbit] frame %d/%d" % (i, FRAMES - 1))
        sys.stdout.flush()

if TIMING:
    # Per-frame CSV, so the distribution can be inspected rather than trusting a single mean -- the
    # orbit is not uniform work, and a mean hides the cost of the frames facing the plume.
    csv = os.path.join(OUT_DIR, "%s_frame_times.csv" % TAG)
    with open(csv, "w") as fh:
        fh.write("frame,ms\n")
        for k, ms in enumerate(times):
            fh.write("%d,%.4f\n" % (k, ms))
    s = sorted(times)
    mean = sum(times) / len(times)
    print("[time] %s  mean %.2f ms (%.1f fps)  median %.2f  p95 %.2f  min %.2f  max %.2f  -> %s"
          % (TAG, mean, 1000.0 / mean, s[len(s) // 2], s[int(len(s) * 0.95)], s[0], s[-1], csv))
    # MUST exit explicitly. Mogwai's main loop keeps running once the script returns, so without this
    # the timing pass finishes its ~1 minute of work and then idle-spins forever -- which looked
    # exactly like a slow renderer (11 minutes wall against 152 s of CPU) and was not one. The capture
    # branch below already exits via clock.exitFrame; this branch had nothing.
    m.clock.exitFrame = WARM + FRAMES + 2
    m.renderFrame()
else:
    # Texture::captureToFile writes ASYNCHRONOUSLY. Quitting on the final captured frame truncates it,
    # so hold for a margin before exiting -- the same reason vr.capture() adds 60.
    m.clock.exitFrame = WARM + FRAMES + 60
    for _ in range(60):
        m.renderFrame()
    print("[orbit] done, %d frames in %s" % (FRAMES, OUT_DIR))
sys.stdout.flush()
