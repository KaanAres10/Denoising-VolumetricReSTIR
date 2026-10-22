# The glowing construct (still volume) under a MOVING camera, through a denoiser (paper spec 2026-10-20, E7): the camera
# about the vertical axis at VR_CAM_DEG degrees a frame and reaches the shot's own view exactly at the captured frame
# (after VR_WARM frames), so the capture scores against the still shot's path-traced reference -- while ReSTIR's temporal
# reuse and the denoiser have seen the camera move all along. Writes c.schedule.json for the capture.
#   VR_SCENE=lanternglow VR_DENOISER=rr VR_CAM_DEG=0.1 VR_OUT_DIR=... (+ the vr_graph knobs: VR_MUTATIONS ...)
import json
import math
import os
import sys

_HERE = r"C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts"
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from falcor import *
import vr_graph as vr

vr.bind(m)
NAME = vr.env("VR_SCENE", "lanternglow")
W, H = vr.env_size("VR_DISPLAY", (960, 540))
OUT_DIR = os.environ["VR_OUT_DIR"]
DENOISER = vr.env("VR_DENOISER", "rr").lower()
DEG = vr.env_float("VR_CAM_DEG", 0.1)

scene = vr.load_scene(NAME)
m.scene.camera.animated = False
cam = m.scene.camera
p0, t0 = cam.position, cam.target
radius = math.sqrt((p0.x - t0.x) ** 2 + (p0.z - t0.z) ** 2)
a0 = math.atan2(p0.x - t0.x, p0.z - t0.z)  # the shot's own view

params = {"mInitialLightSamples": 1, "mFinalLightSamples": 1, "mEnableTemporalReuse": True, "mEnableSpatialReuse": True}
g = RenderGraph("cam_pose")
restir = vr.add_restir(g, scene, render=(W, H), guides=True, mOutputDepth=True, mMotionVecMode="Deterministic",
                       mParams=params)
if DENOISER == "none":  # (raw: ReSTIR's own output, no denoiser's history)
    channel = restir + ".accumulated_color"
else:
    channel = vr.add_denoiser(g, DENOISER, restir + ".accumulated_color", scene, (W, H), (W, H), restir=restir,
                              gbuffer=None, guides=True, preset=vr.env("VR_PRESET", "E"), sdk_variant=vr.env("VR_SDK", "Current"))
g.markOutput(channel)
m.addGraph(g)
m.resizeSwapChain(W, H)
m.ui = False
vr.pin_clock(30)

warm = vr.env_int("VR_WARM", 300)


def place(k):  # the camera k frames before the capture: k x DEG degrees back along the orbit
    a = a0 - math.radians(DEG * k)
    cam.position = float3(t0.x + radius * math.sin(a), p0.y, t0.z + radius * math.cos(a))
    cam.target = t0


place(warm)
m.renderFrame()
f0 = int(m.clock.frame)
capture = f0 + warm
os.makedirs(OUT_DIR, exist_ok=True)
m.frameCapture.outputDir = OUT_DIR
m.frameCapture.baseFilename = "c"
m.frameCapture.addFrames(g, [capture])
with open(os.path.join(OUT_DIR, "c.schedule.json"), "w") as fh:
    json.dump({"scene": NAME, "mode": "camera", "display": [W, H], "first": f0, "captures": [capture], "deg_per_frame": DEG,
               "channel": channel, "chains": [{"frames": [capture]}],
               "env": {k: v for k, v in sorted(os.environ.items()) if k.startswith(("VR_", "LANTERN_"))}}, fh, indent=1)
print("[cam_pose] %s through %s: %.3f deg a frame for %d frames, capture %d at the shot's view" % (NAME, DENOISER, DEG, warm, capture))
m.clock.exitFrame = capture + 3
for k in range(warm, -6, -1):  # the frame rendered with the camera k frames before the capture
    place(k)
    if k == 0:
        print("[cam_pose] the shot's view rendered at clock frame %d (capture %d)" % (int(m.clock.frame), capture))
    m.renderFrame()
