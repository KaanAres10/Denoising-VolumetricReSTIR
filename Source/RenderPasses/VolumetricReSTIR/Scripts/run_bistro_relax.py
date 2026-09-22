# Bistro on the split NRD path, INTERACTIVE, so the denoiser can be judged by moving the camera
# rather than from a metric.
#
# Every measurement in Source/RenderPasses/NRDPass/STATE.md was taken on a fixed orbit; this is the
# same configuration with the camera left in your hands. Drive it with WASD + mouse. The artifacts
# worth looking for, in the order they were found:
#
#   * the plume going see-through, so the building shows through the smoke  (fixed)
#   * a halo of the plume's glow spreading past its own silhouette          (fixed)
#   * hard rectangular seams cutting into the plume's boundary              (fixed)
#   * whole regions of the image shifting brightness together as you move   (fixed: NRD's matrices
#     were reaching the shaders transposed, so RELAX rejected every reprojection)
#   * bulbs and string lights strobing                                      (NOT fixed -- this is
#     the estimator's stochastic emission, and no denoiser removes it; see STATE.md)
#
# Marked outputs, switchable live from Mogwai's Graphs panel (open a second view to compare two at
# once):
#
#   ToneMapper/TAA output       what you would ship
#   ModulateIllumination.output the composite before tonemap and TAA
#   accumulated_color           raw ReSTIR, undenoised -- the noise floor to judge against
#   NRD.validation              NRD's own diagnostic overlay, when VR_NRD_VALIDATION=1
#
#   VR_SCENE=bistro|plume                            which scene. plume is the one with NO measurement
#                                                    against the fixed build yet.
#
# Env switches worth knowing (all have measured defaults, see STATE.md):
#   VR_NRD_METHOD=RelaxDiffuseSh | ReblurDiffuseSh   which denoiser
#   NRD4_RAW_MATRICES=1                              restores the BUG: NRD's matrix constants are read
#                                                    as they arrive, which is transposed. RELAX's
#                                                    history collapses from 29.8 frames to 0.05 on a
#                                                    static camera. This is the real before/after.
#   NRD4_DISOCC=2                                    disocclusion threshold, percent. 2 is NRD's
#                                                    documented value and is now the default; it used
#                                                    to be 35 to work around the bug above.
#   VR_MARK_DEBUG=1                                  also mark the raw HDR buffers (undenoised, the
#                                                    two halves, the pre-tonemap composite). They look
#                                                    BLACK unless you raise exposure in Mogwai.
#   VR_NRD_VALIDATION=1                              add NRD's overlay as an output
#   VR_DENOISER=rr                                   DLSS Ray Reconstruction instead of NRD
#   VR_SDK=Current | Previous310_7                   rr: which nvngx_dlssd.dll -- 310.9.1 (presets D/E/F,
#                                                    F = RR2) or 310.7.0 (D/E). Fixed for the process;
#                                                    open two windows to see both at once.
#   VR_PRESET=E                                      rr: starting preset. Switch live in the DLSSDPass
#                                                    UI; the log prints "preset hint N" on every switch.
#   VR_DISPLAY=1920x1080                             resolution; the recorded orbits are 1920x1080
#   VR_WINDOW_POS=x,y                                where the window opens (its content area's top-left,
#                                                    in screen pixels). rr_compare_windows.cmd uses it to
#                                                    put two windows side by side.
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

RENDER = vr.env_size("VR_DISPLAY", (1280, 720))
MODE = vr.env("VR_DENOISER", "nrd").lower()

# VR_SCENE picks the scene. Kept in this script rather than a second copy because everything below --
# the marked outputs, the exposure, the split -- is identical, and two copies drift.
#
# plume is the case that still has NO measurement against the fixed build, and it is the one most
# likely to disagree with bistro: animated, 1 spp, and genuinely firefly-heavy, which is exactly what
# the anti-firefly setting was originally tuned for (on plume, before the matrix fix).
SCENE = vr.env("VR_SCENE", "bistro").lower()
# The graph name is what Mogwai's Graphs panel shows, so it names the denoiser actually wired below.
# It was SCENE + "_relax" whatever ran -- an RR window read "bistro_relax". For rr it carries the SDK
# variant (fixed per process), not the preset, which can change live: DLSSDPass shows that, plus the
# DLL version actually loaded, on its "Running:" line.
_GRAPH_KIND = {"rr": "RR_" + vr.env("VR_SDK", "Current"),
               "nrd": "NRD_" + vr.env("VR_NRD_METHOD", "RelaxDiffuseSh")}
g = RenderGraph(SCENE + "_" + _GRAPH_KIND.get(MODE, MODE))
scene = vr.load_scene(SCENE)
# RR: every pass follows the WINDOW, so resizing it at runtime keeps colour, depth and guides the same
# size. Pinned to RENDER, the G-buffer and guides stayed put while the estimator followed the window,
# and RR combined misregistered inputs -- garbage, with a "DLSSDPass: input 'depth' is 960x540 but
# color is 2560x1351" warning per size. VR_DISPLAY still sets the size the window opens at. NRD keeps
# the fixed size: its volume blur radius is derived from the render height when the graph is built.
LIVE_SIZE = None if MODE == "rr" else RENDER
restir = vr.add_restir(g, scene, render=LIVE_SIZE, guides=True, mOutputDepth=True,
                       mMotionVecMode="Deterministic")
PRESET = vr.env("VR_PRESET", "E")
SDK_VARIANT = vr.env("VR_SDK", "Current")
out = vr.add_denoiser(g, MODE, restir + ".accumulated_color", scene, LIVE_SIZE, LIVE_SIZE,
                      restir=restir, guides=True, preset=PRESET, sdk_variant=SDK_VARIANT)
tm = vr.add_tonemapper(g, out, exposure=scene.get("exposure", 0.0))
if vr.env_bool("VR_TAA_LDR", True):
    g.addPass(createPass("TAA", vr.taa_props()), "TAA_LDR")
    g.addEdge(tm, "TAA_LDR.colorIn")
    # Same motion vectors as capture_orbit.py (see the measurements there): the estimator's volume-
    # aware mvec, since the G-buffer's describe the wall behind the smoke. VR_TAA_VOLMV=0 restores the
    # G-buffer's, which is what this script used before the orbit script switched.
    g.addEdge((restir + ".mvec") if vr.env_bool("VR_TAA_VOLMV", True) else "GBufferRaster.mvec", "TAA_LDR.motionVecs")
    tm = "TAA_LDR.colorOut"

g.markOutput(tm)

# Everything below this point is an HDR buffer, and bistro is a night exterior that needs +8 EV
# (2^8 = 256x) before anything but the emissive lights is visible -- the tonemapper supplies that, and
# these outputs are BEFORE it. Marking them all by default meant the window could come up on one of
# them, showing a black frame with a few coloured bulbs and no volume or surfaces, which reads exactly
# like a broken render and is not one.
#
# So they are opt-in now. VR_MARK_DEBUG=1 brings them back for A/B work; switch between them in
# Mogwai's Graphs panel, and remember they will look black until you raise exposure there.
if vr.env_bool("VR_MARK_DEBUG", False):
    # The undenoised image, so the denoiser is judged against the noise floor rather than from memory.
    g.markOutput(restir + ".accumulated_color")
if vr.env_bool("VR_MARK_DEBUG", False) and MODE == "nrd":
    g.markOutput("ModulateIllumination.output")
    # The two halves separately. The surface half is where the flicker lived, and the composite hides
    # it, because it mixes in the medium and the raw emissive strobe and then TAA flattens what
    # survives. Switch to it in the Graphs panel to see the denoiser's own output rather than the
    # blend.
    # Default must MATCH add_denoiser's own (False), or without the env this marks passes the graph
    # never created and the script dies with "Can't find render pass 'NRDSurface'".
    if vr.env_bool("VR_NRD_SPLIT", False):
        g.markOutput("NRDSurface.filteredDiffuseRadianceHitDist")
        g.markOutput("NRDVolume.filteredDiffuseRadianceHitDist")
        g.markOutput(restir + ".surfaceColor")

m.addGraph(g)
m.resizeSwapChain(RENDER[0], RENDER[1])
m.ui = True
# setWindowPos is a global from `falcor` (SampleApp binds it), not a method on m; a no-op when headless.
_pos = vr.env("VR_WINDOW_POS", "")
if "," in _pos:
    setWindowPos(int(_pos.split(",")[0]), int(_pos.split(",")[1]))

# Deliberately does NOT name the default value: it is set in NRDPass.cpp and has already moved twice
# (2 -> 20 -> 35), so a number repeated here goes stale silently and misreports what you are looking at.
print("[look] scene=%s denoiser=%s method=%s  disocclusionThreshold=%s  split=%s%s"
      % (SCENE, MODE, vr.env("VR_NRD_METHOD", "RelaxDiffuseSh"),
         (vr.env("NRD4_DISOCC") + "%") if vr.env("NRD4_DISOCC") else "NRDPass default",
         vr.env("VR_NRD_SPLIT", "1"),
         ("  rr preset=%s sdk=%s" % (PRESET, SDK_VARIANT)) if MODE == "rr" else ""))
print("[look] move the camera with WASD + mouse; switch outputs in the Graphs panel")
sys.stdout.flush()

# VR_EXIT_FRAME=N renders N frames and quits, which is how this script gets smoke-tested headless
# before being handed over as a working task. Unset leaves it interactive, which is the point of it.
_EXIT = vr.env_int("VR_EXIT_FRAME", 0)
if _EXIT > 0:
    m.clock.exitFrame = _EXIT
    for _ in range(_EXIT):
        m.renderFrame()
    print("[look] rendered %d frames and exiting (VR_EXIT_FRAME)" % _EXIT)
    sys.stdout.flush()
