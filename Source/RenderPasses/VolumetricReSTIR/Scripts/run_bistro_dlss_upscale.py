# Bistro + Volumetric ReSTIR + DLSS with REAL upscaling (Phase 3) -- the configuration that is
# actually faster, and the one the fixed-compute-budget study needs.
#
# ReSTIR renders below display resolution and DLSS reconstructs to full resolution. Every pixel not
# traced is budget you can spend on sampling instead (mInitialM, spatial rounds, finer mips), which
# is exactly the trade-off this project measures.
#
# Unlike run_bistro_dlss.py (Phase 1, which bolts on a GBufferRaster and gives no speed-up), the
# depth and motion vectors here come from VolumetricReSTIR itself and describe the MEDIUM as well as
# the geometry -- E[t] falls back to the opaque surface hit where the smoke is thin, so a surface
# scene like Bistro is covered end to end. Set VR_GUIDES=gbuffer to A/B against the Phase 1 sidecar.
#
# ---------------------------------------------------------------------------------------------
# RESOLUTION -- three ways to set it, in priority order:
#
#   VR_RENDER=1112x626    explicit render size, wins over everything else
#   VR_SCALE=0.5          fraction of the display size (0.5 => quarter the pixels)
#   VR_PROFILE=Balanced   otherwise derived from the DLSS profile's nominal ratio
#
#   VR_DISPLAY=1920x1080  the reconstruction target (default 1920x1080)
#
# 4K, AND WHY IT IS CAPPED BY YOUR MONITOR
#
# DLSS reconstructs to the SWAPCHAIN size, the swapchain cannot exceed the window, and the window
# cannot exceed the monitor. So on a 1440p screen, VR_DISPLAY=3840x2160 silently gives you the
# window size instead -- verified: it produced 2564x1570, not 3840x2160.
#
#   On a 4K monitor:  VR_DISPLAY=3840x2160     works as expected.
#   On a smaller one: you cannot get 4K out of DLSSPass as it stands (see below).
#
# VR_DLSS_OUTPUT=Fixed is the theoretical escape hatch -- DLSSPass would then output at its own
# renderSize/ratio into an offscreen texture, independent of the swapchain. It is KNOWN BROKEN in
# this build: the output size is only known after NGX initialises, so the pass calls
# requestRecompile() mid-frame ("this causes a one frame delay", DLSSPass.cpp:235-240) and Mogwai
# throws "Can't fetch the output ... the graph wasn't successfully compiled yet" on frame 1.
# Making it work needs a scriptable fixedOutputSize on DLSSPass plus handling of that recompile
# frame; the hook is left here for when that is done.
#
# The camera aspect ratio is pinned to the RENDER aspect every frame, because Mogwai otherwise
# derives it from the swapchain (Mogwai.cpp:803-805) and a window whose aspect differs from the
# render target would stretch the image.
#
# VR_SCALE=1.0 renders at full display resolution with an otherwise identical graph -- that is the
# control for measuring what the render scale actually buys. Aspect is preserved automatically
# unless VR_RENDER forces otherwise; a mismatch is warned about by the pass.
#
# ---------------------------------------------------------------------------------------------
# DLSS SETTINGS
#
#   VR_PROFILE=Balanced   MaxPerf | Balanced (default) | MaxQuality   (this build has only these 3)
#   VR_SHARPNESS=0.0      -1..1; 0 = off. DLSS 3.5 deprecates its own sharpening -- prefer 0.
#   VR_EXPOSURE=0.0       log2 pre-exposure applied to the colour input
#   VR_HDR=1              input is linear HDR radiance (it is -- DLSS sits before the ToneMapper)
#   VR_DLSS=0             bypass DLSS entirely, keep everything else (isolates its cost/quality)
#
# JITTER: on by default and required for DLSS to resolve sub-pixel detail. The pass owns the jitter
# (scaled by 1/renderDim) and applies the gPrevJitter fix. Measured against path-traced ground
# truth: jitter WITHOUT that fix is 36% worse than no jitter; WITH it, 8% better. Do not set
# mApplyPrevJitter=false unless you are reproducing that experiment.
#
#   VR_JITTER=0           disable jitter (softer image; use only as a control)
#
# CAPTURE: VR_CAPTURE_FRAME=N, VR_TAG=name, VR_OUT_DIR=path
#
# Run:  Mogwai.exe --script run_bistro_dlss_upscale.py
#       (or VS Code -> Run Task -> "Run: bistro + DLSS (Balanced upscale)")

import os

from falcor import *

DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"


def _flag(name, default):
    return os.environ.get(name, default) not in ("0", "", "false", "False")


def _size(name, default):
    """Parse WxH (e.g. 1112x626); returns default if unset or malformed."""
    v = os.environ.get(name, "")
    if "x" in v.lower():
        try:
            w, h = v.lower().split("x")
            return (int(w), int(h))
        except ValueError:
            print("[dlss] WARNING: could not parse " + name + "='" + v + "', using default")
    return default


PROFILE = os.environ.get("VR_PROFILE", "Balanced")
if PROFILE not in ("MaxPerf", "Balanced", "MaxQuality"):
    print("[dlss] WARNING: unknown profile '" + PROFILE + "', falling back to Balanced")
    PROFILE = "Balanced"

JITTER = _flag("VR_JITTER", "1")
USE_DLSS = _flag("VR_DLSS", "1")
GUIDES = os.environ.get("VR_GUIDES", "volume").lower()   # volume | gbuffer
# Denoiser between ReSTIR and DLSS. DLSS is an UPSCALER, not a denoiser -- NVIDIA's own reference
# pipeline (scripts/PathTracerNRD.py) denoises first and upscales second. Feeding raw 1-spp ReSTIR
# straight into DLSS leaves most of the noise: measured on Bistro, DLSS alone cuts noise ~29%
# (TV 11.06 -> 7.80), which is nowhere near enough for surfaces lit by ~20k emissive triangles.
DENOISER = os.environ.get("VR_DENOISER", "OIDNGPUPass")   # none | OIDNGPUPass | OIDNCPUPass | OptixDenoiser
SHARPNESS = float(os.environ.get("VR_SHARPNESS", "0.0"))
EXPOSURE = float(os.environ.get("VR_EXPOSURE", "0.0"))
IS_HDR = _flag("VR_HDR", "1")

DISPLAY = _size("VR_DISPLAY", (1920, 1080))

# Nominal DLSS render-scale ratios per profile. The driver decides the real ones at runtime
# (queryOptimalSettings); DLSSPass' UI reports what it actually chose, so check on the first run.
RATIO = {"MaxPerf": 0.5, "Balanced": 0.58, "MaxQuality": 2.0 / 3.0}[PROFILE]
RATIO = float(os.environ.get("VR_SCALE", RATIO))
# Round to even to avoid odd-sized dispatch edges.
RENDER = (int(DISPLAY[0] * RATIO) // 2 * 2, int(DISPLAY[1] * RATIO) // 2 * 2)
RENDER = _size("VR_RENDER", RENDER)   # explicit override wins

# 'Default' = reconstruct to the swapchain (capped by your monitor). 'Fixed' = reconstruct to
# DLSS's own natural size, renderSize/ratio, into an offscreen texture -- the only way to produce
# an image larger than the display.
DLSS_OUTPUT = "Fixed" if os.environ.get("VR_DLSS_OUTPUT", "Default").lower() == "fixed" else "Default"
if DLSS_OUTPUT == "Fixed":
    print("[dlss] WARNING: VR_DLSS_OUTPUT=Fixed is known broken in this build -- DLSSPass triggers a")
    print("[dlss]          mid-frame requestRecompile() and Mogwai throws on frame 1. See the header.")
_EXPECTED_OUT = (int(RENDER[0] / RATIO), int(RENDER[1] / RATIO)) if DLSS_OUTPUT == "Fixed" else DISPLAY

m.loadScene(DATA_DIR + r"\Bistro_5_1\BistroExterior.fbx")

# Dense smoke plume (fork's original parameters). sigma_s=80 is what gives the plume its density,
# structure and coloured scattering -- thinning it out washes both the detail and the colour away.
m.scene.addGVDBVolume(sigma_a=float3(10, 10, 10), sigma_s=float3(80, 80, 80), g=0.0,
                      dataFile=DATA_DIR + r"\smoke-plume-2", numMips=4)

m.scene.camera.position = float3(-15.149291, 8.352362, -8.399609)
m.scene.camera.target = float3(-14.742913, 8.025879, -7.546224)
m.scene.camera.up = float3(0.004061, 0.999961, 0.007782)


def render_graph():
    g = RenderGraph("Bistro DLSS upscale")

    use_gbuffer = GUIDES == "gbuffer"

    vr = createPass("VolumetricReSTIR", {
        # Render below display resolution -- the entire source of the performance win.
        'outputSize': 'Fixed',
        'fixedOutputSize': RENDER,
        # This pass owns the jitter, scaled by 1/renderDim. Leave it to the GBuffer only when the
        # GBuffer is the one producing the guides (setPatternGenerator is global, last writer wins).
        'samplePattern': ('Center' if use_gbuffer else ('Halton' if JITTER else 'Center')),
        'sampleCount': 32,
        # Volume-aware guides; skipped entirely when the GBuffer supplies them.
        'mOutputDepth': not use_gbuffer,
        'mDepthAsNDC': _flag("VR_DEPTH_NDC", "0"),
        'mMotionVecMode': 'Deterministic' if not use_gbuffer else 'Off',
        'mParams': {
            'mUseSurfaceScene': True,        # shade the Bistro geometry (surface-scene path)
            'mUseEmissiveLights': True,      # the scene's many emissive lights
            'mUseEnvironmentLights': False,  # night scene, no sky contribution
            'mTemporalReuseMThreshold': 10.0,
        }})
    g.addPass(vr, "VolumetricReSTIR")

    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 8.0})
    g.addPass(tm, "ToneMapper")

    if not USE_DLSS:
        # Bypass: same reduced-resolution render, no reconstruction. The output stays at RENDER size,
        # so this is the "what does DLSS actually add" control rather than a like-for-like image.
        src = "VolumetricReSTIR.accumulated_color"
        if DENOISER not in ("none", "None", ""):
            g.addPass(createPass(DENOISER), "Denoiser")
            di, do = ("color", "output") if DENOISER == "OptixDenoiser" else ("src", "dst")
            g.addEdge(src, "Denoiser." + di)
            src = "Denoiser." + do
        g.addEdge(src, "ToneMapper.src")
        g.markOutput("ToneMapper.dst")
        return g

    # motionVectorScale MUST be 'Relative': our motion vectors are normalized [0,1], while the
    # DLSSPass default is 'Absolute' (pixels).
    dlss = createPass("DLSSPass", {
        'enabled': True,
        'profile': PROFILE,
        'motionVectorScale': 'Relative',
        'isHDR': IS_HDR,
        'sharpness': SHARPNESS,
        'exposure': EXPOSURE,
        # 'Default' reconstructs to the swapchain (a genuine upscale, since the producer is now
        # smaller). 'Fixed' reconstructs to renderSize/ratio instead, which is how you exceed the
        # monitor's resolution -- see the VR_DLSS_OUTPUT note at the top.
        'outputSize': DLSS_OUTPUT})
    g.addPass(dlss, "DLSSPass")

    # Denoise BEFORE upscaling, matching the reference pipeline. Both operate on linear HDR
    # radiance, so the ToneMapper stays last.
    color_src = "VolumetricReSTIR.accumulated_color"
    if DENOISER not in ("none", "None", ""):
        dn = createPass(DENOISER)
        g.addPass(dn, "Denoiser")
        d_in, d_out = ("color", "output") if DENOISER == "OptixDenoiser" else ("src", "dst")
        g.addEdge(color_src, "Denoiser." + d_in)
        # OptiX has an optional temporal mode; without motion vectors it denoises each frame
        # independently and flickers. Feed it the same mvec DLSS gets -- the pass converts the
        # convention itself (ConvertMotionVectorInputs.cs.slang negates and scales to pixels,
        # because OptiX expects vectors pointing FORWARD in time while DLSS/Falcor point
        # current->previous). OIDN has no motion-vector input in this build.
        if DENOISER == "OptixDenoiser" and not use_gbuffer:
            g.addEdge("VolumetricReSTIR.mvec", "Denoiser.mvec")
        elif DENOISER == "OptixDenoiser":
            g.addEdge("GBufferRaster.mvec", "Denoiser.mvec")
        color_src = "Denoiser." + d_out

    g.addEdge(color_src, "DLSSPass.color")

    if use_gbuffer:
        # Phase 1 style: opaque-geometry guides. Must match the render size, so the GBuffer is
        # pinned to it too. Its jitter generator is the active one in this configuration.
        gb = createPass("GBufferRaster", {'outputSize': 'Fixed', 'fixedOutputSize': RENDER,
                                          'samplePattern': 'Halton' if JITTER else 'Center',
                                          'sampleCount': 32})
        g.addPass(gb, "GBufferRaster")
        g.addEdge("GBufferRaster.depth", "DLSSPass.depth")
        g.addEdge("GBufferRaster.mvec", "DLSSPass.mvec")
    else:
        g.addEdge("VolumetricReSTIR.linearZ", "DLSSPass.depth")
        g.addEdge("VolumetricReSTIR.mvec", "DLSSPass.mvec")

    g.addEdge("DLSSPass.output", "ToneMapper.src")
    g.markOutput("ToneMapper.dst")
    return g


_pix = 100.0 * (RENDER[0] * RENDER[1]) / float(DISPLAY[0] * DISPLAY[1])
print("[dlss] bistro profile=" + PROFILE
      + " render=" + str(RENDER[0]) + "x" + str(RENDER[1])
      + " -> DLSS " + DLSS_OUTPUT + " out~" + str(_EXPECTED_OUT[0]) + "x" + str(_EXPECTED_OUT[1])
      + " (" + str(int(round(_pix))) + "% of " + str(DISPLAY[0]) + "x" + str(DISPLAY[1]) + " traced)"
      + " denoiser=" + DENOISER + " guides=" + GUIDES
      + " jitter=" + ("Halton" if JITTER else "off")
      + (" DLSS=BYPASSED" if not USE_DLSS else ""))

m.addGraph(render_graph())
m.resizeSwapChain(DISPLAY[0], DISPLAY[1])
m.ui = True

# Pin the camera aspect to the RENDER aspect. Mogwai re-derives it from the swapchain on every
# resize (Mogwai.cpp:803-805), so without this a window whose aspect differs from the render target
# -- which is guaranteed when the requested display exceeds the monitor and gets clamped -- stretches
# the image. Re-asserted every frame so a window resize cannot silently undo it.
_ASPECT = RENDER[0] / float(RENDER[1])


def _pin_aspect(scene, t):
    if abs(scene.camera.aspectRatio - _ASPECT) > 1e-4:
        scene.camera.aspectRatio = _ASPECT


m.sceneUpdateCallback = _pin_aspect

# Optional capture: VR_CAPTURE_FRAME=N writes the reconstructed frame at display resolution.
_cap = int(os.environ.get("VR_CAPTURE_FRAME", "0"))
if _cap > 0:
    _out = os.environ.get("VR_OUT_DIR", r"C:\research\Denoising-VolumetricReSTIR\shots\dlss_gallery")
    os.makedirs(_out, exist_ok=True)
    m.frameCapture.outputDir = _out
    m.frameCapture.baseFilename = os.environ.get("VR_TAG", "bistro_dlss_" + PROFILE.lower())
    m.frameCapture.addFrames(m.activeGraph, [_cap])
