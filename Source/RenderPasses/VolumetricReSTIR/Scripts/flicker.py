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
SPEED = vr.env_float("VR_FLICK_SPEED", 0.02)

g = RenderGraph("flicker")
scene = vr.load_scene("bistro")
restir = vr.add_restir(g, scene, render=RENDER, guides=True, mOutputDepth=True,
                       mMotionVecMode="Deterministic")
color = restir + ".accumulated_color"
out = vr.add_denoiser(g, "nrd", color, scene, RENDER, RENDER, restir=restir, guides=True,
                      nrd_enabled=vr.env_bool("VR_NRD_ENABLED", True))
tm = vr.add_tonemapper(g, out, exposure=scene.get("exposure", 0.0))
g.markOutput(tm)
m.addGraph(g)
m.resizeSwapChain(RENDER[0], RENDER[1])
m.ui = True
vr.pin_clock()

# Fixed, reproducible camera path: a steady dolly. Deterministic per frame index, so two runs with
# different denoiser settings see byte-identical camera motion and the comparison is fair.
cam = m.scene.camera
p0 = cam.position
t0 = cam.target
d = float3(t0.x - p0.x, t0.y - p0.y, t0.z - p0.z)


def place(i):
    s = SPEED * i
    cam.position = float3(p0.x + d.x * s, p0.y + d.y * s, p0.z + d.z * s)
    cam.target = float3(t0.x + d.x * s, t0.y + d.y * s, t0.z + d.z * s)


out_dir = os.environ["VR_OUT_DIR"]
os.makedirs(out_dir, exist_ok=True)
m.frameCapture.outputDir = out_dir
m.frameCapture.baseFilename = "fl"
m.frameCapture.addFrames(g, [WARM + k for k in range(N)])

# Without this Mogwai never quits after the loop -- it is an interactive app, and the run just hangs
# until something kills it.
m.clock.exitFrame = WARM + N + 60
print("[flicker] warm=%d capture=%d..%d speed=%.3f" % (WARM, WARM, WARM + N - 1, SPEED))
sys.stdout.flush()
for i in range(WARM + N + 60):
    place(i)
    m.renderFrame()
