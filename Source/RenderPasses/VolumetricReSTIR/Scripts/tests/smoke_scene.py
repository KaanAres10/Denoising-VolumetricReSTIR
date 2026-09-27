# Renders VR_SCENE for a few frames and captures the raw estimator output (test_smoke_scenes.py checks it).
#
#   VR_SCENE=<name> VR_OUT_DIR=<dir> Mogwai.exe --script smoke_scene.py
import os
import sys

_HERE = r"C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts"
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from falcor import *
import vr_graph as vr

vr.bind(m)

NAME = vr.env("VR_SCENE", "plume")
OUT_DIR = os.environ["VR_OUT_DIR"]
W, H = 640, 360
FRAMES = 8

scene = vr.load_scene(NAME)
g = RenderGraph("smoke_" + NAME)
restir = vr.add_restir(g, scene, render=(W, H))
g.markOutput(restir + ".accumulated_color")
m.addGraph(g)
m.resizeSwapChain(W, H)
m.ui = False
vr.pin_clock(30)

m.renderFrame()
f = int(m.clock.frame) + FRAMES
os.makedirs(OUT_DIR, exist_ok=True)
m.frameCapture.outputDir = OUT_DIR
m.frameCapture.baseFilename = NAME
m.frameCapture.addFrames(g, [f])
m.clock.exitFrame = f + 60
for _ in range(FRAMES + 64):
    m.renderFrame()
