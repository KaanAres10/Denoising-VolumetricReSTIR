# Mogwai half of the diagnostics check (test_diagnostics_capture.py reads what this writes).
#
# Renders the static plume and captures the 6th frame of three chains, seeded A, B, A through the
# `frameSeed` property, with the `sampleIdentity` output marked. A reseeded chain must replay its
# frames exactly, a different seed must not, and the identity channel must be well formed.
#
#   VR_OUT_DIR=<dir> Mogwai.exe --script check_diagnostics.py
import json
import os
import sys

_HERE = r"C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts"
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from falcor import *
import vr_graph as vr

vr.bind(m)

OUT_DIR = os.environ["VR_OUT_DIR"]
W, H = 640, 360
SEEDS = [1000, 2000, 1000]
CHAIN = 6  # frames per chain; the last one is captured

scene = vr.load_scene("plume")
g = RenderGraph("check_diagnostics")
restir = vr.add_restir(g, scene, render=(W, H))
g.markOutput(restir + ".accumulated_color")
g.markOutput(restir + ".sampleIdentity")
m.addGraph(g)
m.resizeSwapChain(W, H)
m.ui = False
vr.pin_clock(30)

m.renderFrame()  # settle
f0 = int(m.clock.frame)
captures = [f0 + c * CHAIN + CHAIN for c in range(len(SEEDS))]
os.makedirs(OUT_DIR, exist_ok=True)
m.frameCapture.outputDir = OUT_DIR
m.frameCapture.baseFilename = "diag"
m.frameCapture.addFrames(g, captures)
with open(os.path.join(OUT_DIR, "diag.frames.json"), "w") as fh:
    json.dump({"seeds": SEEDS, "frames": captures}, fh)
m.clock.exitFrame = captures[-1] + 60
for c, seed in enumerate(SEEDS):
    g.get_pass("VolumetricReSTIR").set_properties({"frameSeed": seed})
    for _ in range(CHAIN):
        m.renderFrame()
for _ in range(64):
    m.renderFrame()
