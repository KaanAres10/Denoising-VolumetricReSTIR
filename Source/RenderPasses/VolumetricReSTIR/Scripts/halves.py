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
# VR_ORBIT=1 drives bistro's authored orbit before capturing, because the artifact this script
# exists to diagnose only appears under camera motion -- on the static default camera RELAX and
# REBLUR are visually identical. Measuring the halves on the static frame was measuring the regime
# where nothing is wrong.
FRAME = vr.env_int("VR_CAPTURE_FRAME", 40)
if vr.env_bool("VR_ORBIT", False):
    import math
    cam = m.scene.camera
    cx, cy, cz = -11.0, 6.025879, 0.0
    p0 = cam.position
    r = math.sqrt((p0.x - cx) ** 2 + (p0.z - cz) ** 2)
    y, a0 = p0.y, math.atan2(p0.z - cz, p0.x - cx)
    step = (-180.0 * math.pi / 180.0) / 99.0
    for i in range(FRAME):
        a = a0 + step * i
        cam.position = float3(cx + r * math.cos(a), y, cz + r * math.sin(a))
        cam.target = float3(cx, cy, cz)
        m.renderFrame()
    # Hold the final pose for the capture frame itself.
    a = a0 + step * FRAME
    cam.position = float3(cx + r * math.cos(a), y, cz + r * math.sin(a))
    cam.target = float3(cx, cy, cz)
    print("[halves] orbited %d frames, r=%.2f" % (FRAME, r))
    sys.stdout.flush()

vr.capture(g, FRAME if not vr.env_bool("VR_ORBIT", False) else FRAME + 1,
           os.environ["VR_OUT_DIR"], "hv", exit_after=True)
