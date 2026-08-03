# Measures FLICKER under camera motion, which is the symptom nothing so far has actually measured.
#
# Every NRD number in this project was taken on a PINNED camera. That is the one regime where
# history is never disoccluded, so it cannot see the artifact being complained about. Here the camera
# moves on a fixed path and several CONSECUTIVE frames are captured; flicker is the frame-to-frame
# difference of a converged-by-then denoiser output.
import os
import sys

_HERE = r"C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts"
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from falcor import *
import vr_graph as vr

vr.bind(m)

RENDER = vr.env_size("VR_DISPLAY", (1280, 720))
WARM = vr.env_int("VR_FLICK_WARM", 40)     # frames of motion before capturing, so history is settled
N = vr.env_int("VR_FLICK_N", 6)            # consecutive frames to capture
SPEED = vr.env_float("VR_FLICK_SPEED", 0.012)   # radians/frame for the orbit

g = RenderGraph("flicker")
scene = vr.load_scene("bistro")
restir = vr.add_restir(g, scene, render=RENDER, guides=True, mOutputDepth=True,
                       mMotionVecMode="Deterministic")
color = restir + ".accumulated_color"
# VR_DENOISER selects which denoiser is under test. The camera path, warm-up and capture frames are
# identical whichever is chosen, so sequences from different denoisers are directly comparable.
MODE = vr.env("VR_DENOISER", "nrd").lower()
out = vr.add_denoiser(g, MODE, color, scene, RENDER, RENDER, restir=restir, guides=True,
                      nrd_enabled=vr.env_bool("VR_NRD_ENABLED", True))
tm = vr.add_tonemapper(g, out, exposure=scene.get("exposure", 0.0))
# VR_TAA_LDR=1 puts temporal AA AFTER the tonemapper instead of before it. Not cosmetic: TAA fetches
# history with a bicubic Catmull-Rom filter, whose negative lobes on raw HDR produce negative values
# that clamp to zero and lose energy -- measured as a 36% drop in mean brightness when TAA ran on the
# linear signal. Tonemapping first bounds the range, which is where TAA is normally applied.
if vr.env_bool("VR_TAA_LDR", False):
    g.addPass(createPass("TAA"), "TAA_LDR")
    g.addEdge(tm, "TAA_LDR.colorIn")
    g.addEdge("GBufferRaster.mvec", "TAA_LDR.motionVecs")
    tm = "TAA_LDR.colorOut"
g.markOutput(tm)
m.addGraph(g)
m.resizeSwapChain(RENDER[0], RENDER[1])
m.ui = True
vr.pin_clock()

# Fixed, reproducible camera path: a steady dolly. Deterministic per frame index, so two runs with
# different denoiser settings see byte-identical camera motion and the comparison is fair.
cam = m.scene.camera

# Bistro's authored reference orbit, taken from the pre-Falcor-8 capture script rather than invented:
# a 180-degree sweep around a point out in the plaza, at constant height, always looking at it.
#
#     ORBIT_CENTER = (-11.0, 6.025879, 0.0)   radius ~9.37   -180 degrees over 300 frames
#
# The centre matters and is NOT the camera's target. Bistro's target sits 0.95 units from the camera,
# so orbiting around IT is the camera spinning on the spot -- which disoccludes violently and made
# every denoiser score ~4x worse. That was a property of the path, not of rotation.
import math

ORBIT_CENTER = (-11.0, 6.025879, 0.0)
ORBIT_DEGREES = vr.env_float("VR_ORBIT_DEG", -180.0)
ORBIT_FRAMES = vr.env_int("VR_ORBIT_FRAMES", 300)

_cx, _cy, _cz = ORBIT_CENTER
_p = cam.position
_radius = math.sqrt((_p.x - _cx) ** 2 + (_p.z - _cz) ** 2)
_y = _p.y                      # constant height, as in the original
_a0 = math.atan2(_p.z - _cz, _p.x - _cx)
_step = (ORBIT_DEGREES * math.pi / 180.0) / max(1, ORBIT_FRAMES - 1)
print("[flicker] orbit r=%.3f about (%.2f,%.2f,%.2f), %.4f rad/frame"
      % (_radius, _cx, _cy, _cz, _step))


def place(i):
    a = _a0 + _step * i
    cam.position = float3(_cx + _radius * math.cos(a), _y, _cz + _radius * math.sin(a))
    cam.target = float3(_cx, _cy, _cz)


out_dir = os.environ["VR_OUT_DIR"]
os.makedirs(out_dir, exist_ok=True)
m.frameCapture.outputDir = out_dir
m.frameCapture.baseFilename = "fl"
m.frameCapture.addFrames(g, [WARM + k for k in range(N)])

# Without this Mogwai never quits after the loop -- it is an interactive app, and the run just hangs
# until something kills it.
m.clock.exitFrame = WARM + N + max(60, vr.env_int('VR_TIME_N', 60) + 3)
print("[flicker] warm=%d capture=%d..%d speed=%.3f" % (WARM, WARM, WARM + N - 1, SPEED))
sys.stdout.flush()
# VR_TIME=1 also reports frame cost. Wall clock and END TO END (CPU submit + GPU + present), so it
# is an upper bound rather than a GPU-only figure -- Mogwai exposes no device to Python, so Falcor's
# profiler is unreachable from a script. Timed over the same camera path as the image capture, after
# a warm-up, so denoisers are compared doing identical work.
import time

TIME_N = vr.env_int("VR_TIME_N", 60) if vr.env_bool("VR_TIME", False) else 0
t_start = None
for i in range(WARM + N + max(60, TIME_N + 3)):
    place(i)
    if TIME_N and i == WARM + N:
        m.renderFrame()          # one untimed frame so the capture flush is not counted
        t_start = time.perf_counter()
        continue
    m.renderFrame()
    if TIME_N and t_start is not None and i == WARM + N + TIME_N:
        dt = (time.perf_counter() - t_start) / TIME_N
        print("[time] %.3f ms/frame over %d frames" % (dt * 1000.0, TIME_N))
        sys.stdout.flush()
        t_start = None
