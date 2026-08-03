# Capture the two halves of the split SEPARATELY, so "the smoke looks transparent" can be attributed
# to one of them instead of guessed at from the composite.
import os
import sys

_HERE = r"C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts"
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from falcor import *
import vr_graph as vr

vr.bind(m)

RENDER = vr.env_size("VR_DISPLAY", (1280, 720))
g = RenderGraph("halves")
scene = vr.load_scene("bistro")
restir = vr.add_restir(g, scene, render=RENDER, guides=True, mOutputDepth=True,
                       mMotionVecMode="Deterministic")
out = vr.add_denoiser(g, "nrd", restir + ".accumulated_color", scene, RENDER, RENDER,
                      restir=restir, guides=True)
g.markOutput(out)
# Each NRDPass instance's filtered output, before compositing.
g.markOutput("NRDSurface.filteredDiffuseRadianceHitDist")
g.markOutput("NRDVolume.filteredDiffuseRadianceHitDist")
g.markOutput(restir + ".mediumAlpha")
g.markOutput(restir + ".volumeColor")
g.markOutput(restir + ".surfaceColor")

m.addGraph(g)
m.resizeSwapChain(RENDER[0], RENDER[1])
m.ui = True
vr.pin_clock()
vr.capture(g, vr.env_int("VR_CAPTURE_FRAME", 40), os.environ["VR_OUT_DIR"], "hv", exit_after=True)
