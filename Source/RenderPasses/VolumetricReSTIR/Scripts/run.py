# One script for every combination. Built from vr_graph.py, so a new scene or denoiser is one entry
# in a dict there rather than another run_*.py here.
#
#   VR_SCENE=plume        plume | bistro
#   VR_DENOISER=rr        none | oidn | oidncpu | optix | sr | rr
#   VR_UPSCALE=1          THE SWITCH: 1 renders below display resolution and reconstructs, 0 is native
#   VR_PROFILE=Balanced   MaxPerf | Balanced | MaxQuality  -- sets both the ratio and the DLSS profile
#   VR_RATIO=             override the ratio directly (0.25 .. 1.0); VR_PROFILE still sets the profile
#   VR_DISPLAY=1920x1080  output resolution (capped by the window -- a swapchain cannot exceed it)
#   VR_VOLGUIDES=1        RR only: blend volumetric guides (0 = surface guides only, for the A/B)
#   VR_PRESET=E           RR render preset: D or E
#   VR_TONEMAP=1          0 leaves the output linear HDR, which is what MSE comparisons need
#   VR_CAPTURE_FRAME=0    >0 captures that frame and the run is otherwise unattended
#   VR_REFERENCE=0        brute-force path tracing, accumulated -- ignores VR_DENOISER
#   VR_FRAMERATE=60       pins animation to frame/framerate; 0 leaves it on the wall clock
#   VR_HOLD_AT=0          >0 = per-frame reference workflow (see below)
#   VR_HOLD_SAMPLES=3000  reference only: samples accumulated on the held frame
#   VR_FREEZE_ANIM=0      freeze the scene at t=0. Converges, but only to the t=0 state, and it
#                         removes the temporal variation NRD's variance estimator needs -- prefer
#                         VR_HOLD_AT for anything that scores a temporal denoiser.
#
# PER-FRAME REFERENCE (VR_HOLD_AT). Scoring a temporal denoiser needs a reference for the same scene
# state the denoiser actually saw, after it has had real frames to build history from. Neither older
# option gives that: freezing at t=0 converges to a state no animated run passes through, and not
# freezing never converges at all (the accumulation averages a different state every frame, so error
# GROWS with samples). VR_HOLD_AT=N animates to frame N and then holds:
#
#   reference:  VR_REFERENCE=1 VR_HOLD_AT=200 VR_HOLD_SAMPLES=3000   -> captures at 200+3000
#   denoised :  VR_DENOISER=nrd VR_HOLD_AT=200                       -> captures at 200, still animating
#
# Both land on the state at frame N, and VR_FRAMERATE makes N mean the same thing in both runs.
#
# Upscaling and denoising are independent switches, which is the point: `rr` with VR_UPSCALE=0 is RR
# as a pure denoiser at native resolution (DLAA), and with VR_UPSCALE=1 it denoises AND upscales in
# the same stage. Everything is adjustable live in Mogwai afterwards -- the pass UI has the same
# switch, so this only sets the starting point.
#
# Run:  VR_SCENE=plume VR_DENOISER=rr VR_UPSCALE=1 Mogwai.exe --script run.py

# Falcor execs scripts without setting __file__ and without putting the script's directory on
# sys.path, so this preamble is required before importing anything from this folder.
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

vr.bind(m)  # the module cannot see Mogwai's `m` on its own

SCENE = vr.env("VR_SCENE", "plume").lower()
MODE = vr.env("VR_DENOISER", "rr").lower()
UPSCALE = vr.env_bool("VR_UPSCALE", False)
PROFILE = vr.env("VR_PROFILE", "Balanced")
RATIO = vr.env_float("VR_RATIO", None)
DISPLAY = vr.env_size("VR_DISPLAY", (1920, 1080))
VOLGUIDES = vr.env_bool("VR_VOLGUIDES", True)
PRESET = vr.env("VR_PRESET", "E")
TONEMAP = vr.env_bool("VR_TONEMAP", True)
REFERENCE = vr.env_bool("VR_REFERENCE", False)
# nrd only: 0 bypasses the denoiser (NRDPass blits input->output), leaving just the
# demodulate/re-modulate round trip -- an identity check on the adapter.
NRD_ENABLED = vr.env_bool("VR_NRD_ENABLED", True)
# Super Resolution only. Current = 310.7.0 transformer, LegacyCNN = 3.7.20 convolutional -- the only
# way to reach a CNN, since the 310.x line removed every CNN preset. Ray Reconstruction has no legacy
# equivalent at all: no 3.x SDK ever shipped nvngx_dlssd.dll.
SDK_VARIANT = vr.env("VR_SDK", "Current")
SR_PRESET = vr.env("VR_SR_PRESET", "Default")
CAPTURE = vr.env_int("VR_CAPTURE_FRAME", 0)

EFFECTIVE_RATIO = RATIO if RATIO is not None else vr.PROFILE_RATIO.get(PROFILE, 0.58)
# Only used for the passes that cannot take a ratio (and for the log line); the DLSS chain is driven
# by EFFECTIVE_RATIO so it stays correct when the real window differs from DISPLAY.
RENDER = vr.render_size(DISPLAY, PROFILE, UPSCALE, RATIO)
# Only DLSS can put the pixels back. Anything else would hand the swapchain an undersized image.
if UPSCALE and MODE not in ("sr", "rr") and not REFERENCE:
    print("[run] VR_UPSCALE=1 needs VR_DENOISER=sr or rr -- '%s' does not upscale. Rendering native." % MODE)
    UPSCALE, RENDER = False, DISPLAY


def render_graph():
    g = RenderGraph("%s %s%s" % (SCENE, "reference" if REFERENCE else MODE, " upscaled" if UPSCALE else ""))

    # Jitter is owned by the GBuffer whenever there is one (DLSS graphs); otherwise nobody needs it,
    # and it changes what is being estimated, so it stays off.
    # NRD needs the volume guides too: scatterDistance rides the same gate, and it needs linearZ as
    # its viewZ, which mOutputDepth controls. RR takes depth from the G-buffer instead, hence the
    # asymmetry.
    restir = vr.add_restir(g, scene, upscale=UPSCALE, profile=PROFILE, ratio=EFFECTIVE_RATIO,
                           guides=(MODE in ("rr", "nrd") and VOLGUIDES), jitter=False,
                           reference=REFERENCE,
                           # Deterministic mvec is enabled so VR_NRD_VOLMV=1 has something to read --
                           # the pass defaults to Off, and an unconnected output would hand NRD an
                           # empty texture, i.e. "nothing moved". Costs one write when unused. See the
                           # mvec note in vr_graph.add_denoiser for why VR_NRD_VOLMV defaults off.
                           **({"mOutputDepth": True, "mMotionVecMode": "Deterministic"}
                              if MODE == "nrd" else {}))
    color = restir + ".accumulated_color"

    if REFERENCE:
        g.markOutput(vr.add_accumulator(g, color))
        return g

    # One ratio for the estimator, the G-buffer and the guides. Passing the ratio rather than a size
    # is what makes fullscreen work: each pass resolves it against the REAL swapchain, which the
    # script cannot query, so a size computed here would be wrong whenever the window manager does
    # not grant exactly VR_DISPLAY.
    out = vr.add_denoiser(g, MODE, color, scene, RENDER, DISPLAY, profile=PROFILE, preset=PRESET,
                          upscale_ratio=EFFECTIVE_RATIO,
                          restir=restir, guides=VOLGUIDES,
                          sdk_variant=SDK_VARIANT, sr_render_preset=SR_PRESET,
                          nrd_enabled=NRD_ENABLED)
    exposure = scene.get("exposure", 0.0)
    if TONEMAP:
        g.markOutput(vr.add_tonemapper(g, out, exposure=exposure))
    else:
        # VR_TONEMAP=0 exists so MSE is measured on linear HDR. But a linear night exterior is
        # BLACK on screen -- bistro needs +8 EV -- and an unviewable window is indistinguishable
        # from a broken render, which has already cost one long hunt through the estimator and the
        # render scale (see vr_graph.add_tonemapper). So mark the linear channel for measurement AND
        # a tonemapped one purely to look at. sweep.py picks by channel name and does not know about
        # ToneMapper.dst, so the extra channel cannot be mistaken for the measured result; the only
        # cost is one small PNG per captured frame.
        g.markOutput(out)
        # VR_VIEW_TONEMAP=0 omits the viewable channel entirely. Adding a pass changes the render
        # graph, so this exists to compare against numbers measured before the channel existed.
        if vr.env_bool("VR_VIEW_TONEMAP", True):
            g.markOutput(vr.add_tonemapper(g, out, exposure=exposure, name="ViewToneMapper"))

    # The undenoised estimate, so a black frame can be attributed to the estimator or to the
    # denoiser chain rather than guessed at.
    g.markOutput(color)

    # Marked so every guide is inspectable in Mogwai's output dropdown.
    if MODE == "rr":
        for ch in ("diffuseAlbedo", "specularAlbedo", "normals", "roughness"):
            g.markOutput("DLSSDGuides." + ch)
        if VOLGUIDES:
            g.markOutput(restir + ".mediumAlpha")
    return g


scene = vr.load_scene(SCENE)

print("[run] scene=%s denoiser=%s upscale=%s  %dx%d -> %dx%d (%.0f%% of the pixels)%s"
      % (SCENE, "reference" if REFERENCE else MODE, "on" if UPSCALE else "off",
         RENDER[0], RENDER[1], DISPLAY[0], DISPLAY[1], 100 * vr.pixel_fraction(RENDER, DISPLAY),
         "" if not UPSCALE else "  profile=" + PROFILE))

m.addGraph(render_graph())
m.resizeSwapChain(DISPLAY[0], DISPLAY[1])
m.ui = True

# Frame-deterministic animation time. Must happen before any frame is rendered.
FPS = vr.pin_clock()

# VR_HOLD_AT=N animates to frame N and holds that state. This is how a per-frame reference is built,
# and it is the only setup in which a temporal denoiser can be scored fairly: the denoised run gets N
# frames of genuine animation to accumulate history from, and the reference converges on the state at
# N. See vr_graph.advance_and_hold for why the two older options (freeze at 0 / never freeze) cannot
# do this. Capture lands at N + VR_HOLD_SAMPLES, since the hold frames are rendered here.
HOLD_AT = vr.env_int("VR_HOLD_AT", 0)
if HOLD_AT > 0:
    if REFERENCE:
        HOLD_SAMPLES = vr.env_int("VR_HOLD_SAMPLES", 3000)
        # An animated sequence must be pinned too -- it is driven by the rendered-frame count, not
        # the clock, so the clock hold alone would leave it advancing under the accumulation.
        vr.advance_and_hold(HOLD_AT,
                            volume_frames=vr.env_int("VR_ANIM_FRAMES", 100) if vr.env_bool("VR_ANIMATED", False) else None)
        CAPTURE = HOLD_AT + HOLD_SAMPLES
        print("[run] holding scene at frame %d (fps=%s), accumulating %d samples, capture at %d"
              % (HOLD_AT, FPS, HOLD_SAMPLES, CAPTURE))
    else:
        # The denoised run must NOT hold: the animation is what gives NRD the temporal variation its
        # variance estimator needs. It only has to arrive at the same frame N the reference holds.
        CAPTURE = HOLD_AT
        print("[run] animating to frame %d (fps=%s), capture there" % (HOLD_AT, FPS))
    sys.stdout.flush()

TIME_FRAMES = vr.env_int("VR_TIME_FRAMES", 0)
if TIME_FRAMES > 0:
    # Wall-clock frame time. This is END-TO-END (CPU submit + GPU + present), not a GPU-only
    # profiler figure: Mogwai exposes no device to Python, so Falcor's profiler is unreachable from
    # a script. Over many frames the pipeline saturates and the average tracks GPU cost closely, but
    # it is an upper bound and should be reported as such. NRDPass in particular forces a
    # command-list flush every frame, a sync the other denoisers do not pay -- that cost is real and
    # belongs in the number.
    import time

    WARMUP = vr.env_int("VR_TIME_WARMUP", 60)
    for _ in range(WARMUP):
        m.renderFrame()
    _t0 = time.perf_counter()
    for _ in range(TIME_FRAMES):
        m.renderFrame()
    _ms = (time.perf_counter() - _t0) * 1000.0 / TIME_FRAMES
    print("[timing] %.3f ms/frame over %d frames (after %d warmup)" % (_ms, TIME_FRAMES, WARMUP))
    sys.stdout.flush()
    m.clock.exitFrame = WARMUP + TIME_FRAMES + 2
else:
    vr.capture(m.activeGraph, CAPTURE,
               vr.env("VR_OUT_DIR", vr.REPO + r"\shots\run"),
               vr.env("VR_TAG", "%s_%s%s" % (SCENE, "reference" if REFERENCE else MODE, "_up" if UPSCALE else "")),
               exit_after=vr.env_bool("VR_EXIT_AFTER_CAPTURE", False))
