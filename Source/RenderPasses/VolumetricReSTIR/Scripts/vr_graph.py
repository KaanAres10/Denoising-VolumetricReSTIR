# Composable building blocks for the denoiser / upscaler experiments.
#
# Everything that was copy-pasted across a dozen run_*.py scripts lives here once: the DLSS ratio
# table (it was duplicated in six scripts), the scene setups, and the wiring for each denoiser.
# Adding a scene or a denoiser is one entry in a dict and every script gets it.
#
# Falcor execs scripts without setting __file__ AND without putting the script's directory on
# sys.path, so an importing script needs this preamble first -- the path fix cannot live in here,
# since that is what you are trying to import:
#
#     import os, sys
#     _HERE = r"C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts"
#     try:
#         _HERE = os.path.dirname(os.path.abspath(__file__))
#     except NameError:
#         pass
#     if _HERE not in sys.path:
#         sys.path.insert(0, _HERE)
#
#     from falcor import *
#     import vr_graph as vr
#     vr.bind(m)
#
# See run.py, which is the entry point for every scene/denoiser/upscale combination.

import os
import sys

from falcor import *

# Mogwai injects `m` into the executing SCRIPT's globals, which an imported module does not share --
# so the script has to hand it over once, with vr.bind(m), before calling anything here.
m = None


def bind(mogwai):
    """Give this module the Mogwai instance. Call once, immediately after importing."""
    global m
    m = mogwai


REPO = r"C:\research\Denoising-VolumetricReSTIR"
DATA_DIR = REPO + r"\VolumetricReSTIRData"
SCRIPT_DIR = REPO + r"\Source\RenderPasses\VolumetricReSTIR\Scripts"

try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    pass
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


# ---------------------------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------------------------

def env(name, default=""):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.lower() not in ("0", "off", "no", "false")


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_size(name, default):
    """VR_DISPLAY=1920x1080 -> (1920, 1080)."""
    v = os.environ.get(name, "")
    if "x" in v.lower():
        try:
            w, h = v.lower().split("x")
            return (int(w), int(h))
        except ValueError:
            pass
    return default


# ---------------------------------------------------------------------------------------------
# Render scale
# ---------------------------------------------------------------------------------------------

# Linear ratio per DLSS profile; the PIXEL count is its square, which is the number that matters for
# the compute budget. DLAA is native (no upscaling), and is the right choice when measuring DLSS as
# a pure denoiser.
# Keys are the SDK names (which is what the pass properties take); the comment gives NVIDIA's UI name,
# since only that tells you what a user would call it.
PROFILE_RATIO = {
    "DLAA": 1.0,                       # DLAA               100% of the pixels
    "UltraQuality": 1.0 / 1.3,         # (never shipped)     59%
    "MaxQuality": 2.0 / 3.0,           # Quality             44%
    "Balanced": 0.58,                  # Balanced            34%
    "MaxPerf": 0.5,                    # Performance         25%
    "UltraPerformance": 1.0 / 3.0,     # Ultra Performance   11%
}


def render_size(display, profile="Balanced", upscale=True, ratio=None):
    """Display size -> render size. `upscale=False` is the off switch: render natively.

    Deliberately identical (including the even-rounding) to VolumetricReSTIR::upscaledRenderSize on
    the C++ side, so a graph built with `upscale=True` on the pass and a GBuffer sized from this
    function agree exactly. Ray Reconstruction requires that -- its guide textures must match the
    colour input pixel for pixel.
    """
    if not upscale:
        return tuple(display)
    r = ratio if ratio is not None else PROFILE_RATIO.get(profile, 0.58)
    return (max(32, int(display[0] * r) // 2 * 2), max(32, int(display[1] * r) // 2 * 2))


def pixel_fraction(render, display):
    return float(render[0] * render[1]) / float(display[0] * display[1])


# The passes name their presets descriptively now (a bare letter tells you nothing, and the letters
# mean different networks for RR and SR). Scripts and env vars may still use the plain letter.
RR_PRESETS = {"Default": "Default", "D": "D_Transformer", "E": "E_TransformerLatest"}
# A..F are the convolutional models and exist only in the LegacyCNN (3.7.20) DLL; J..M are the
# transformer models and exist only in Current (310.7.0). Pairing a letter with the wrong SDK variant
# does not fail -- NGX quietly substitutes that DLL's default.
SR_PRESETS = {"Default": "Default",
              "A": "A_CNN", "B": "B_CNN", "C": "C_CNN", "D": "D_CNN", "E": "E_CNN", "F": "F_CNN",
              "J": "J_TransformerLessGhost", "K": "K_TransformerBestQuality",
              "L": "L_TransformerUltraPerf", "M": "M_TransformerPerf"}


def rr_preset(name):
    """'E' -> 'E_TransformerLatest'. Already-expanded names pass through unchanged."""
    return RR_PRESETS.get(name, name)


def sr_preset(name):
    return SR_PRESETS.get(name, name)


# ---------------------------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------------------------

def load_plume(frame="0198"):
    """Plume on a bare ground plane, lit by the environment only.

    The measurement scene: no geometry to speak of, so the medium covers essentially every pixel and
    the volumetric guides are what RR actually sees.

    VR_ANIMATED=1 loads the fire115 SEQUENCE instead of a single frame. That distinction decides
    whether a temporal denoiser can be measured at all: NRD's RELAX gates its spatial filtering on a
    TEMPORALLY estimated variance, so on a static scene it concludes the signal is already converged
    and declines to filter -- `phiLuminance` 2 vs 32 measured 1.6e-14 apart, i.e. numerically
    identical. Every NRD number taken on the static frame is from the one regime where NRD does
    nothing. See Source/RenderPasses/NRDPass/README.md.

    Loading a sequence also sets `hasAnimation` (it is DERIVED from the per-frame path, not a
    parameter), which is what gates the velocity-advected motion vectors and ReSTIR's previous-grid
    reprojection.
    """
    m.loadScene(DATA_DIR + r"\default.obj")
    m.scene.setEnvMap(DATA_DIR + r"\hansaplatz_8k.hdr")
    # Shared by both paths so the two cannot drift apart.
    vol = dict(sigma_a=float3(6, 6, 6), sigma_s=float3(14, 14, 14), g=0.0,
               numMips=4, densityScale=0.1, hasEmission=False, LeScale=0.01,
               temperatureCutoff=900.0, temperatureScale=0.0,
               worldTranslation=float3(0, 1.686, 0), worldRotation=float3(0, 0, 0),
               worldScaling=0.013)
    if env_bool("VR_ANIMATED", False):
        # hasVelocity MUST match how the frames were baked (GVDBBake ... 4 1 0 ...), or the loader
        # reads velocity grids that are not in the file.
        # Every frame is loaded eagerly and stays GPU-RESIDENT at ~28 MB, so numFrames is a VRAM
        # budget, not just a length: 100 frames is ~2.8 GB before any denoiser allocates.
        m.scene.addGVDBVolumeSequence(
            dataFilePrefix=DATA_DIR + "\\fire115\\fire115.", numberFixedLength=4,
            startFrame=env_int("VR_ANIM_START", 100), numFrames=env_int("VR_ANIM_FRAMES", 100),
            hasVelocity=True, **vol)
    else:
        m.scene.addGVDBVolume(
            dataFile=DATA_DIR + "\\fire115\\fire115." + frame,
            hasVelocity=False, **vol)
    # Detach the camera from the scene's animation FIRST. Bistro's FBX drives the camera, and an
    # animated camera silently overwrites whatever is assigned below -- the view then wanders on
    # wall-clock time, so the same script gives a different shot on every run, and a shot facing the
    # night sky is indistinguishable from broken lighting.
    m.scene.camera.animated = False
    m.scene.camera.position = float3(1.977354, 2.411630, 2.242076)
    m.scene.camera.target = float3(1.366226, 2.220231, 1.474033)
    m.scene.camera.up = float3(0.0, 1.0, 0.0)
    # The depth range MUST be set explicitly. Scene::resetCamera derives it as farZ = sceneBB.radius
    # * 50, and the GVDB volume is not part of the mesh bounding box -- only default.obj is, a plane
    # small enough that the derived far plane comes out at 0.354 while the medium sits 0.35..3.4 units
    # away. Two consequences, both of which read as denoiser problems rather than camera problems:
    #   * GBufferRaster clips essentially everything, so its linearZ output is ALL ZEROS. That is the
    #     depth NRD was being handed, and a zero depth makes RELAX's reprojection degenerate.
    #   * The estimator's "no medium" fallback writes farZ, putting the background NEARER than the
    #     smoke -- a flat, close surface for NRD to blur across, which is the background smearing.
    m.scene.camera.nearPlane = 0.1
    m.scene.camera.farPlane = 1000.0
    return {
        # sigma_s / sigma_t = 14 / (14 + 6): the single-scatter albedo, RR's diffuse guide for the
        # medium. A uniform, not a texture -- only density varies spatially in this renderer.
        "scatterAlbedo": float3(0.7, 0.7, 0.7),
        # Daylight environment map: no compensation needed.
        "exposure": 0.0,
        "params": {"mUseEnvironmentLights": True, "mUseEmissiveLights": False},
    }


def load_bistro():
    """Bistro exterior, emissive-lit, with a dense smoke plume. The surface-heavy counterpart."""
    m.loadScene(DATA_DIR + r"\Bistro_5_1\BistroExterior.fbx")
    m.scene.addGVDBVolume(sigma_a=float3(10, 10, 10), sigma_s=float3(80, 80, 80), g=0.0,
                          dataFile=DATA_DIR + r"\smoke-plume-2", numMips=4)
    # Detach the camera from the scene's animation FIRST. Bistro's FBX drives the camera, and an
    # animated camera silently overwrites whatever is assigned below -- the view then wanders on
    # wall-clock time, so the same script gives a different shot on every run, and a shot facing the
    # night sky is indistinguishable from broken lighting.
    m.scene.camera.animated = False
    m.scene.camera.position = float3(-15.149291, 8.352362, -8.399609)
    m.scene.camera.target = float3(-14.742913, 8.025879, -7.546224)
    m.scene.camera.up = float3(0.004061, 0.999961, 0.007782)
    return {
        "scatterAlbedo": float3(0.888, 0.888, 0.888),   # 80 / (80 + 10)
        # Night exterior lit only by emissive geometry: without this the frame is 256x too dark.
        "exposure": 8.0,
        "params": {"mUseSurfaceScene": True, "mUseEmissiveLights": True,
                   "mUseEnvironmentLights": False, "mTemporalReuseMThreshold": 10.0},
    }


SCENES = {"plume": load_plume, "bistro": load_bistro}


def load_scene(name):
    """Load a scene by name.

    Each loader detaches the CAMERA from the scene's animation (see load_bistro): Bistro's FBX drives
    the camera, which otherwise overrides the scripted position and advances on wall-clock time, so
    "frame 200" is a different shot in every run -- and a shot facing the night sky is
    indistinguishable from broken lighting.

    Deliberately does NOT set `m.scene.animated = False`. That is a bigger hammer than it looks: it
    stops the scene update the emissive LightCollection and the volume rely on, and the result is a
    frame with nothing but directly-visible emitters -- which reads as a lighting bug, not as a
    frozen scene. Pinning the camera is enough for deterministic captures.
    """
    if name not in SCENES:
        raise ValueError("unknown scene '%s' (have: %s)" % (name, ", ".join(sorted(SCENES))))
    scene = SCENES[name]()
    # Freezing the scene's own animations is REQUIRED for an accumulated ground truth: Bistro's FBX
    # animates, so accumulating N frames averages N different scene states and the result never
    # converges -- it drifts. Measured: 500-vs-3000 differed by 4.7e-4 while 3000-vs-30000 differed
    # by 8.1e-4, i.e. getting further apart with more samples, which is the signature of a moving
    # target rather than a noisy one.
    if env_bool("VR_FREEZE_ANIM", False):
        m.scene.animated = False
    return scene


# ---------------------------------------------------------------------------------------------
# Graph pieces
# ---------------------------------------------------------------------------------------------

def add_restir(g, scene, upscale=False, profile="Balanced", ratio=None, guides=False,
               jitter=False, reference=False, name="VolumetricReSTIR", render=None, **params):
    """The estimator. Returns the pass name.

    `render` pins an explicit size and MUST be used whenever another pass in the graph is sized to
    match -- which is every DLSS graph, since Ray Reconstruction needs its guides pixel-aligned with
    the colour. The pass's own `upscale` switch resolves its ratio against the real swapchain, while
    a sibling GBufferRaster can only be given a number computed from the *requested* display. Those
    two agree until the window manager refuses the requested size, and then RR silently receives
    colour and guides at different resolutions. Pinning both to one number removes the second source
    of truth. The ratio switch remains the right control interactively, where nothing shadows it.

    `jitter=False` leaves the camera jitter to whoever else installs a pattern (the GBuffer, in every
    DLSS graph): Camera::setPatternGenerator is global and last-writer-wins, so two passes both
    claiming it silently fight.
    """
    props = {
        "upscale": bool(upscale) and render is None,
        "upscaleRatio": ratio if ratio is not None else PROFILE_RATIO.get(profile, 0.58),
        "samplePattern": "Halton" if jitter else "Center",
        "sampleCount": 32,
        "mOutputVolumeGuides": bool(guides),
        # What goes into the medium's guide normal. The default reproduces the previous behaviour
        # (-rayDir), which carries no volume information at all; "gradient" writes the density
        # gradient. Left as a switch because the gradient was rejected once on stated grounds and
        # that objection deserves a measurement.
        "mVolumeNormalMode": "Gradient" if env("VR_VOL_NORMAL", "camera").lower() == "gradient" else "Camera",
        # Knee of the volume-half confinement mask, cov = saturate(mediumAlpha / knee). SMALLER is
        # gentler: the mask reaches 1 sooner, so more of the plume's genuine soft edge survives.
        # Measured leak ratio (ring+12 / core) against raw's 0.3262: knee 0.5 gives 0.2208 (over-
        # confined, eats real wisps), knee 0.2 gives 0.3260. 0.2 is the default on that basis.
        "coverageKnee": env_float("VR_NRD_COVKNEE", 0.2),
        "mParams": dict(scene.get("params", {})),
    }
    # The reference is brute-force path tracing: no reuse, accumulated over thousands of frames.
    props["mParams"].update({
        "mUseReference": bool(reference),
        "mEnableTemporalReuse": not reference,
        "mEnableSpatialReuse": not reference,
    })
    for k, v in params.items():
        if k == "mParams":
            props["mParams"].update(v)
        else:
            props[k] = v
    g.addPass(createPass("VolumetricReSTIR", props), name)
    return name


def add_gbuffer(g, render, jitter=True, name="GBufferRaster", upscale=False, ratio=None):
    """Depth / motion vectors / guide inputs, at the SAME size as the estimator.

    Prefer `upscale`+`ratio` over the fixed `render` size. A fixed size is derived from the display
    resolution the script *asked* for, and the window manager does not have to honour it -- fullscreen
    is the common case. The ratio resolves against the real swapchain inside the pass, so estimator,
    G-buffer and guides all land on the same number whatever the window turns out to be.
    """
    props = {"samplePattern": "Halton" if jitter else "Center", "sampleCount": 32}
    if upscale:
        props.update({"upscale": True, "upscaleRatio": ratio if ratio is not None else 0.58})
    else:
        props.update({"outputSize": "Fixed", "fixedOutputSize": render})
    g.addPass(createPass("GBufferRaster", props), name)
    return name


def add_rr_guides(g, scene, gbuffer="GBufferRaster", restir=None, render=None, name="DLSSDGuides",
                  upscale=False, ratio=None):
    """G-buffer -> Ray Reconstruction guides, blending in the medium where it covers the pixel.

    `render` must be the same size as the colour handed to DLSSDPass. Left at the graph default the
    guides are allocated at swapchain size, and with upscaling on RR then gets guides misregistered
    by the upscale factor -- visible as silhouette/edge fringing, never as an error.
    """
    props = {"mediumScatterAlbedo": scene["scatterAlbedo"]}
    if upscale:
        props.update({"upscale": True, "upscaleRatio": ratio if ratio is not None else 0.58})
    elif render is not None:
        props.update({"outputSize": "Fixed", "fixedOutputSize": render})
    g.addPass(createPass("DLSSDGuides", props), name)
    for ch in ("diffuseOpacity", "specRough", "guideNormalW", "viewW"):
        g.addEdge(gbuffer + "." + ch, name + "." + ch)
    if restir:
        g.addEdge(restir + ".mediumAlpha", name + ".mediumAlpha")
        g.addEdge(restir + ".mediumNormal", name + ".mediumNormal")
    return name


# Denoisers that are a single pass taking colour in and colour out.
_SIMPLE = {
    "oidn":    ("OIDNGPUPass", "src", "dst"),
    "oidncpu": ("OIDNCPUPass", "src", "dst"),
    "optix":   ("OptixDenoiser", "color", "output"),
}

DENOISERS = ["none", "oidn", "oidncpu", "optix", "sr", "rr", "nrd"]


def taa_props():
    """TAA's two controls.

    WITHDRAWN, and it is worth knowing why: this used to say NRD's own temporal settings were inert on
    this content, because maxAccumulatedFrameNum 30 against 1 moved flicker 0.3%, and concluded that
    TAA was the only lever left. That was true only because NRD's matrices were reaching the shaders
    transposed, so RELAX rejected every reprojection and had no history to lose. With that fixed
    (RELAX_Config.hlsli), the same test on bistro's orbit moves instability at sigma=32 from 7.41 to
    10.57 -- 43%, not 0.3%. NRD's accumulation is doing real work now.

    So treat every "NRD setting X does nothing here" note in this project as measured against a broken
    denoiser until it has been re-run.

    alpha is the weight of the CURRENT frame: lower = longer history = steadier, at the cost of
    ghosting. colorBoxSigma is how far history may stray from the local neighbourhood before it is
    clamped: higher = steadier, at the cost of smearing.

    colorBoxSigma 1.0 -> 2.0, measured on bistro's authored orbit after the matrix fix. It is not the
    trade the line above predicts -- it improves BOTH axes at once:

        colorBoxSigma   s=32   s=128   whole-frame   sharpness
            1.0         7.41    2.74      1.509         75.9
            2.0         6.84    2.36      1.272        119.8
            3.0         6.59    2.20      1.161        148.3
        REBLUR 1.0      7.01    2.51      1.328         92.2
        REBLUR 2.0      6.67    2.30      1.227        126.2

    The reason it is not a trade: with a tight box the clamp drags history toward the local mean every
    frame, and that IS a blur. Widening it lets the converged history survive. Checked for ghosting
    rather than assumed -- frame-to-frame change in the fastest-moving crop RISES with sigma (3.16 ->
    3.30 -> 3.47), where smeared history would make it fall, and there are no trails at 2x zoom.

    Stopped at 2.0 even though 3.0 measures better on every number, because by eye 3.0 puts stippling
    back on the pavement and a crunchy texture in the plume: TAA has stopped clamping enough and noise
    is coming through, which the Laplacian reads as "sharpness". Metrics and eye disagree there, and
    the eye wins.

    alpha is NOT a lever here: 0.1 -> 0.05 moves s=32 by 0.3%.

    This is a TAA change, so it helps REBLUR too (7.01 -> 6.67) and is not a RELAX-specific win. Any
    RELAX-vs-REBLUR comparison must hold it fixed; at a matched 2.0 REBLUR is still 2.5% ahead.
    """
    return {"alpha": env_float("VR_TAA_ALPHA", 0.1),
            "colorBoxSigma": env_float("VR_TAA_SIGMA", 2.0)}


def add_nrd_split(g, color, scene, render, gbuffer, gd, restir, nrd_enabled=True, emission=False):
    """Denoise the medium and the surfaces SEPARATELY, then add them back together.

    The problem this exists to fix, measured on bistro frame 40: NRD reduces Laplacian variance 6.5x
    on a wall and 62x inside the medium, in the same frame at the same settings -- because every
    guide it edge-stops on describes a surface, and inside smoke those guides describe whatever is
    BEHIND the smoke. The visible symptom is not the smoothness; it is that pavement seams and
    building edges are drawn THROUGH the plume, structure the denoiser is inventing from the wall's
    depth and normal.

    Splitting fixes the cause rather than the symptom: the volume half is denoised against the
    medium's own depth and normal, so there are no wall edges in its guides to stamp into the smoke.

    The composite is exact. VolumetricReSTIR's volumeColor + surfaceColor reconstruct
    accumulated_color bit-for-bit (verified: 0.000e+00 over 100% of pixels), and
    ModulateIllumination sums `diffuseReflectance * diffuseRadiance + residualRadiance`. The surface
    half rides the modulated path as before; the volume half goes through residualRadiance, which is
    a plain additive term -- correct, because in-scattered radiance has no surface albedo to divide
    out and multiply back.

    Requires from the estimator: volumeColor, surfaceColor, mediumNormal, linearZ (mOutputDepth) and
    a deterministic mvec (mMotionVecMode="Deterministic").
    """
    sh = env_bool("VR_NRD_SH", False)
    method = env("VR_NRD_METHOD", "RelaxDiffuseSh" if sh else "RelaxDiffuse")

    # Divide the surface half by primary-ray transmittance before denoising, and put it back after.
    # T is the one factor in that buffer a SURFACE denoiser has no business filtering: it varies over
    # a few pixels along the plume's silhouette, which appears in none of NRD's guides, and it belongs
    # to the medium in front of the wall rather than to the wall. Demodulated, the denoiser sees the
    # unoccluded wall -- smooth, no plume-shaped feature at all -- and the occlusion is re-applied
    # from the estimator's own per-pixel T, so the boundary's opacity stops being the accidental
    # outcome of two independently blurred halves.
    surf_demod_tr = env_bool("VR_NRD_SURFTR", True)

    def adapter(name, src, normal_src, demodulate, hitdist_src, transmittance_src=None,
                method_override=None):
        # minReflectance 1.0 makes the divisor exactly 1, because albedo is always <= 1. That is how
        # the volume half opts out of albedo demodulation -- a surface albedo is not a property the
        # in-scattered radiance was ever multiplied by, so dividing by it would be inventing a
        # divisor and the re-modulation would then have to invent the same one back.
        props = {"useScatterDistance": env_bool("VR_NRD_HITDIST", True),
                 "useNormalGuide": env_bool("VR_NRD_NORMALS", True),
                 # Substituted where the hit distance is absent, and fed EVERYWHERE when
                 # VR_NRD_HITDIST=0. The 1000 default sits far past REBLUR's normalisation scale
                 # (f = A + |viewZ|*B, about 4 at these depths), so it saturates -- meaning the
                 # ablation switch feeds a MORE saturated value than the real guide rather than a
                 # neutral one. Exposed so the kernel can actually be driven small.
                 "missHitDistance": env_float("VR_NRD_MISSHIT", 1000.0),
                 # MEASURED WRONG, off by default. The idea was to divide out the rate at which this
                 # half won the reservoir, on the theory that the split's structural zeros bias it
                 # dark. They do not: ReSTIR's own weight W = runningSum/(p_y*M) ALREADY accounts for
                 # selection probability, which is why the two halves sum to accumulated_color
                 # exactly. Dividing again double-corrects. Measured on bistro frame 40 as mean
                 # radiance per coverage band, ratio to raw (1.000 = unbiased):
                 #
                 #     band                    off      on
                 #     thin (0.01-0.25)      0.834   1.576
                 #     partial (0.25-0.75)   0.964   1.397
                 #     dense (>0.75)         0.977   1.155
                 #
                 # i.e. it turns a 17% shortfall into a 58% excess. The transition band's real problem
                 # is VARIANCE, not bias -- the estimator is right on average but is zero most frames
                 # and large occasionally, which is also why turning up diffusePrepassBlurRadius and
                 # historyFixFrameNum made the flicker worse rather than better.
                 "normalizeBySelection": env_bool("VR_NRD_SELNORM", False),
                 "selectionBlur": env_int("VR_NRD_SELBLUR", 5),
                 "selectionFloor": env_float("VR_NRD_SELFLOOR", 0.1),
                 # Luminance ceiling on what NRD is handed. NRDPass's own maxIntensity lives in
                 # PackRadiance, which the SH methods skip entirely, so on this path nothing clamped
                 # -- and NRD asks for HDR inputs in [0; 250] because RELAX tracks second moments.
                 "maxIntensity": env_float("VR_NRD_ADAPT_MAXINT", 250.0)}
        if not demodulate:
            props["minReflectance"] = 1.0
        if transmittance_src:
            props["demodulateTransmittance"] = True
            props["minTransmittance"] = env_float("VR_NRD_MINTR", 0.05)
        if sh:
            props["shMode"] = True
            # Must follow THIS instance's method, not the graph's: REBLUR packs SH0 as YCoCg and
            # RELAX as linear RGB, and neither validates its input, so a mismatch is a green cast
            # rather than an error. That bug has already been shipped here once.
            props["shYCoCg"] = (method_override or method).lower().startswith("reblur")
        if render is not None:
            props.update({"outputSize": "Fixed", "fixedOutputSize": render})
        g.addPass(createPass("NRDAdapter", props), name)
        g.addEdge(src, name + ".color")
        # Each half gets ITS OWN hit distance. Both used to receive the medium's scatterDistance,
        # which told the SURFACE denoiser "the hit is at the scatter point" rather than at the wall.
        # RELAX ignores hit distance entirely with the pre-pass off -- measured byte-identical with
        # VR_NRD_HITDIST=0 -- so it never noticed. REBLUR is hit-distance DRIVEN and sizes its kernel
        # from it, so the bug landed squarely on REBLUR, in exactly the region where the medium is.
        g.addEdge(hitdist_src, name + ".scatterDistance")
        g.addEdge(normal_src, name + ".guideNormalW")
        g.addEdge(gbuffer + ".specRough", name + ".specRough")
        g.addEdge(gd + ".diffuseAlbedo", name + ".diffuseAlbedo")
        if transmittance_src:
            g.addEdge(transmittance_src, name + ".transmittance")
        if sh:
            g.addEdge(restir + ".lightDir", name + ".lightDir")
        return name

    def denoiser(name, adapter_name, viewz_src, mvec_src, accum, phi, confidence_src=None,
                 max_blur=None, method_override=None):
        # Each half gets its OWN tuning. They are not the same problem: the converged medium is 4.3x
        # smoother than the surfaces around it (scale-free gradient energy 56.9 vs 247.2 inside and
        # outside the plume), so the volume half can be filtered harder without destroying anything
        # that is actually there, while the surface half must stay conservative.
        props = {"method": method_override or method,
                 "worldSpaceMotion": False, "maxIntensity": env_float("VR_NRD_MAXINT", 100000.0),
                 "enabled": nrd_enabled,
                 "diffuseMaxAccumulatedFrameNum": accum,
                 "diffusePhiLuminance": phi,
                 # The pre-pass is wrong for BOTH halves and for the same reason: v4 sizes its kernel
                 # as prepassBlurRadius * saturate(hitDist / frustumSize), which assumes a short
                 # secondary-bounce length. Both branches feed a primary distance of the same order as
                 # the frustum, so the factor saturates and the pre-pass degenerates into a
                 # full-radius blur. Measured monotonically bad on RELAX (radius 30 was worse than the
                 # undenoised input); on REBLUR it is most of the halo -- the volume half's energy
                 # 14-30 px OUTSIDE the plume's silhouette goes 2.40x raw -> 1.43x with this at 0.
                 # REBLUR had been running at NRD's default 30 because every tuning decision in this
                 # port was applied to RelaxSettings only.
                 "prepassBlurRadius": env_float("VR_NRD_PREPASS", 0.0)}
        if max_blur is not None:
            props["maxBlurRadius"] = max_blur
        if sh:
            props["shResolveMode"] = env("VR_NRD_SH_RESOLVE", "Dc")
        # NRD's own opinion of the inputs, which is worth more than any amount of tuning against a
        # denoiser that might be reading a bad guide. Nine viewports; the ones that matter here are
        # MV (viewport 3: the provided motion vector reprojected, MINUS the reprojection NRD derives
        # from world position, in pixels -- black is correct, colour is error, blue is off-screen),
        # UNITS & JITTER (viewport 4: a RED dot means the jitter is outside [-0.5; 0.5], i.e. NRD is
        # being told something it cannot use), and DIFF-SPEC FRAMES (viewport 8: accumulated history
        # length, which says whether temporal accumulation is happening at all).
        if env_bool("VR_NRD_VALIDATION", False):
            props["enableValidation"] = True
        g.addPass(createPass("NRD", props), name)
        if sh:
            g.addEdge(adapter_name + ".diffuseSh0", name + ".diffuseSh0")
            g.addEdge(adapter_name + ".diffuseSh1", name + ".diffuseSh1")
        else:
            g.addEdge(adapter_name + ".diffuseRadianceHitDist", name + ".diffuseRadianceHitDist")
        g.addEdge(adapter_name + ".normWRoughnessMaterialID", name + ".normWRoughnessMaterialID")
        g.addEdge(viewz_src, name + ".viewZ")
        g.addEdge(mvec_src, name + ".mvec")
        # NRDPass gates isHistoryConfidenceAvailable on BOTH inputs being connected, so the same
        # texture goes to both slots -- NRD only reads the one its method declares, and a
        # diffuse-only method never touches the specular slot.
        if confidence_src:
            g.addEdge(confidence_src, name + ".diffuseConfidence")
            g.addEdge(confidence_src, name + ".specularConfidence")
        return name

    # --- surface half: exactly the guides RELAX was designed for ---
    # linearZ is RG32Float with view-space Z in .x, which the adapter's single-channel input reads
    # directly. It is a view Z rather than a ray distance -- they differ by the view-direction cosine
    # -- but it describes the SURFACE, which scatterDistance does not.
    a_s = adapter("NRDAdapterSurface", restir + ".surfaceColor",
                  gbuffer + ".guideNormalW", demodulate=env_bool("VR_NRD_DEMOD", True),
                  hitdist_src=gbuffer + ".linearZ",
                  transmittance_src=(restir + ".mediumTransmittance") if surf_demod_tr else None)
    #
    # The surface half also gets primary-ray transmittance as NRD's HISTORY CONFIDENCE, which is what
    # fixes the see-through smoke. The half is T * L_surface, and T belongs to the medium in FRONT of
    # the surface, so it does not travel along the surface's motion vector -- yet every guide the
    # denoiser can test (viewZ, normal, plane distance) describes the wall behind the smoke and says
    # the reprojection is fine. REBLUR therefore keeps drawing the building it saw before the plume
    # moved across it. Measured on bistro's orbit, dense band (mediumAlpha > 0.75), surface half:
    #
    #     raw split 7.2e-4    RELAX 8.3e-4    REBLUR 146.5e-4    REBLUR + confidence 8.3e-4
    #
    # i.e. REBLUR put back twenty times the surface energy that exists there. Forcing
    # maxAccumulatedFrameNum = 1 collapses it to 8.3e-4 and disabling every SPATIAL pass changes
    # nothing (146.2e-4), so it is the temporal reprojection, not the blur. RELAX escapes because its
    # luminance edge-stopping already refuses to blend a bright history against a zero current sample
    # -- which is why confidence costs RELAX nothing (8.2518e-4 -> 8.2409e-4, unchanged outside the
    # plume). The volume half is byte-identical either way; only the surface branch is wired to it.
    #
    # ON by default, unlike every other switch in this file, because it is a correctness fix rather
    # than an experiment. VR_NRD_SURFCONF=0 restores the old behaviour for an A/B.
    n_s = denoiser("NRDSurface", a_s, gbuffer + ".linearZ", gbuffer + ".mvec",
                   env_int("VR_NRD_SURF_ACCUM", 30), env_float("VR_NRD_SURF_PHI", 2.0),
    #
    # With demodulation on, the confidence comes from the ADAPTER rather than from raw transmittance,
    # and the difference is the point. Raw T rejects history everywhere the medium is thick, including
    # where demodulation is already handling it -- measured worse there (composite 4-6 px inside the
    # silhouette: 1.013/1.027 with demodulation alone against 1.067/1.088 with raw-T confidence on
    # top). The adapter instead emits saturate(T / minTransmittance): 1 while the divisor still tracks
    # T, ramping to 0 as it floors out, so each mechanism covers exactly the regime the other cannot
    # and the handover sits at one number rather than two that could drift apart.
                   # VR_NRD_SURF_BLUR sets maxBlurRadius on the surface half. INERT under RELAX:
                   # NRDPass maps the maxBlurRadius property onto mReblurSettings only
                   # (NRDPass.cpp, kMaxBlurRadius), so it does nothing unless this half is running a
                   # Reblur* method. Verified the hard way -- 30, 15 and 8 produced instability
                   # identical to four decimals, which is this project's standing signature for a
                   # knob that is not wired. RELAX's spatial extent is atrousIterationNum, not this.
                   max_blur=(env_float("VR_NRD_SURF_BLUR", 0.0) or None),
                   confidence_src=((a_s + ".historyConfidence") if surf_demod_tr
                                   else (restir + ".mediumTransmittance"
                                         if env_bool("VR_NRD_SURFCONF", True) else None)))

    # --- volume half: the medium's own geometry ---
    #
    # viewZ is the estimator's linearZ, i.e. the view Z of the expected SCATTER point, not the wall
    # behind it. Deliberately not scatterDistance itself: that is a ray distance carrying a -1 "no
    # medium" sentinel, and NRD wants a view-space Z with a valid value everywhere.
    #
    # The normal is mediumNormal. Worth being blunt about what that is: in the default Camera mode it
    # is -rayDir, a pure function of pixel coordinate that carries NO volume information, so the
    # volume denoiser then has a normal guide that cannot reject anything. Set VR_VOL_NORMAL=gradient
    # to get the density gradient instead. Either way it beats the wall's normal, which actively
    # asserts edges that are not in the medium.
    # VR_NRD_VOL_METHOD picks a DIFFERENT denoiser for the medium than for the surfaces, which is a
    # thing the split makes possible and which the measurements ask for. Instability by spatial
    # scale, x1e-3 (the second temporal difference AFTER blurring, so it sees whole regions moving
    # together rather than per-pixel sparkle -- which is the artifact people actually notice when the
    # camera moves, and which the per-pixel metric is blind to by construction):
    #
    #     sigma        0       8      32     128   whole-frame
    #     RELAX    261.8    59.4    19.1     8.4      5.91
    #     REBLUR   233.1    36.3     5.7     2.1      1.16
    #
    # REBLUR is 3.3x steadier at sigma 32 and 5.1x on whole-frame brightness. It is NOT its temporal
    # stabilization pass -- turning that off leaves it at 5.78 vs 5.72, unchanged. The medium is a
    # large smooth region covering 17% of the frame, which is what dominates those coarse scales, and
    # in-medium per-pixel instability is RELAX 0.49x against REBLUR 0.22x.
    vol_method = env("VR_NRD_VOL_METHOD", "") or None
    a_v = adapter("NRDAdapterVolume", restir + ".volumeColor",
                  restir + ".mediumNormal", demodulate=False,
                  hitdist_src=restir + ".scatterDistance", method_override=vol_method)
    #
    # The volume branch gets a TIGHTER max blur radius than NRD's default 30, and it is the halo fix.
    # Nothing in the volume denoiser's guides marks where the plume ends -- mediumNormal goes quiet
    # outside the medium and viewZ falls back to the far plane -- so a wide kernel simply carries the
    # plume's radiance out past its own silhouette. Volume half as a ratio to raw, by signed distance
    # from the silhouette:
    #
    #     band                 6-14 px out   14-30 px out   30-80 px out
    #     prepass 30, blur 30     1.43x          2.40x          3.41x
    #     prepass 0,  blur 30     1.26x          1.43x          0.79x
    #     prepass 0,  blur 12     1.15x          0.91x          0.16x
    #
    # and the plume's INTERIOR gets slightly brighter doing it (0.87 -> 0.88 at -20..-8 px), because
    # the energy stops leaving. RELAX at its own defaults is 1.37 / 1.89 / 17.92 on the same bands,
    # so this is now the better-confined of the two rather than the worse.
    #
    # SCALED BY RESOLUTION, because NRD's blur radius is in PIXELS and 12 was measured at 720p. Left
    # as a bare 12 it would be a much smaller world-space footprint at 4K and a much larger one at
    # 540p -- i.e. the one number here most likely to be silently wrong on someone else's setup. This
    # keeps the footprint constant in world space, which is what a medium's confinement wants; it
    # does NOT make the value scene-independent, since how far the plume's radiance may legitimately
    # spread is a property of the medium, not of the camera.
    vol_blur = env_float("VR_NRD_VOL_BLUR", 12.0 * (render[1] / 720.0) if render else 12.0)
    n_v = denoiser("NRDVolume", a_v, restir + ".linearZ", restir + ".mvec",
                   env_int("VR_NRD_VOL_ACCUM", 30), env_float("VR_NRD_VOL_PHI", 2.0),
                   max_blur=vol_blur, method_override=vol_method)

    # --- composite ---
    # residualRadiance is a plain `outputColor.rgb += ...` term in ModulateIllumination, which is
    # what the volume half needs: no reflectance to multiply back.
    g.addPass(createPass("ModulateIllumination"), "ModulateIllumination")
    g.addEdge(n_s + ".filteredDiffuseRadianceHitDist", "ModulateIllumination.diffuseRadiance")
    # Re-modulate by EXACTLY what the adapter divided by, not by albedo again. Once transmittance is
    # part of the divisor the two are different, and having ModulateIllumination re-derive the formula
    # is how a demodulate/remodulate pair silently stops being a round trip. demodDivisor is the
    # adapter's own record of what it used.
    g.addEdge(a_s + ".demodDivisor" if surf_demod_tr else gd + ".diffuseAlbedo",
              "ModulateIllumination.diffuseReflectance")
    # VR_NRD_VOLMASK confines the volume half to the plume. residualRadiance is purely ADDITIVE, so
    # nothing can attenuate energy the denoiser blurred outside the medium's silhouette -- measured
    # leak ratio (ring+12 / core) raw 0.326, RELAX 0.365, REBLUR 0.401, with REBLUR's core losing 15%
    # of its energy to the halo. The specular pair is unused and is a MULTIPLY, so routing the volume
    # half through it with a coverage mask kills whatever landed outside.
    #
    # The mask is saturate(mediumAlpha / knee), not raw alpha: the core sits near alpha 0.9, so a raw
    # multiply would remove the halo and darken the core ~10% at the same time.
    if env_bool("VR_NRD_VOLMASK", False):
        g.addEdge(n_v + ".filteredDiffuseRadianceHitDist", "ModulateIllumination.specularRadiance")
        g.addEdge(restir + ".mediumCoverage", "ModulateIllumination.specularReflectance")
    else:
        g.addEdge(n_v + ".filteredDiffuseRadianceHitDist", "ModulateIllumination.residualRadiance")
    # Emitters skip both denoisers. FinalShading drops them from the volume/surface pair when
    # emissiveColor is connected, so the three buffers still sum to the original exactly.
    #
    # But NOT filtering them at all is where essentially all of this configuration's flicker comes
    # from, and it took bucketing the per-pixel second temporal difference by what each pixel IS to
    # see it. Before TAA, emitter pixels are 2.55% of the frame and carry 95.7% of the flicker
    # energy -- 37.5x the per-pixel rate -- and 99% of the worst-flickering pixels are emitters. The
    # reason is in FinalShading: emissiveColor is `curColor` only when the reservoir happened to pick
    # self-emission, else zero. Measured over 8 consecutive frames at emitter cores: 76% of
    # pixel-frames are exactly ZERO, 98.4% of pixels are on/off, temporal std/mean is 2.65, and the
    # emissive term is 100% of the composite there. It strobes, and it is added raw.
    #
    # Both existing options are wrong. Bypassed (emission=True) it strobes. Folded back into the
    # denoised path (emission=False) it is demodulated by a diffuse albedo it was never multiplied
    # by, taking the full 100x from the minReflectance floor -- that is the 6.89x bloom.
    #
    # The missing option is to denoise it WITHOUT demodulating it: its own adapter with
    # minReflectance = 1.0 (the divisor is then exactly 1, the same trick the volume half uses to opt
    # out), and a kernel small enough that a point emitter is not smeared back into a bloom.
    if emission:
        if env_bool("VR_NRD_EMISDN", False):
            # ALWAYS REBLUR here, whatever the graph's method is, and the reason is not preference.
            # This branch needs temporal accumulation with as close to NO spatial filtering as the
            # library allows, because any real blur radius smears a point emitter straight back into
            # the bloom that routing emission around the denoiser existed to fix. RELAX cannot do
            # that -- atrousIterationNum is documented "[2; 8]", so its spatial pass cannot be turned
            # off, and running it here measured 6.6% WORSE flicker with sharpness up 21%, which is
            # the bloom's extra gradients. REBLUR can: pre-pass 0 and maxBlurRadius 0 leave only the
            # 1-pixel minBlurRadius floor.
            emis_method = env("VR_NRD_EMIS_METHOD", "ReblurDiffuseSh" if sh else "ReblurDiffuse")
            a_e = adapter("NRDAdapterEmissive", restir + ".emissiveColor",
                          gbuffer + ".guideNormalW", demodulate=False,
                          hitdist_src=gbuffer + ".linearZ", method_override=emis_method)
            # This is the one input in the graph NRD's temporal pass has real work to do on. The
            # surface and volume halves arrive already averaged by VolumetricReSTIR's own temporal
            # reuse -- measured: accumulating 30 frames instead of 1 moves flicker 0.3% -- whereas
            # emissiveColor is re-randomised every frame: at emitter cores 76% of pixel-frames are
            # exactly zero and 98.4% of pixels are on/off.
            n_e = denoiser("NRDEmissive", a_e, gbuffer + ".linearZ", gbuffer + ".mvec",
                           env_int("VR_NRD_EMIS_ACCUM", 30), env_float("VR_NRD_EMIS_PHI", 2.0),
                           max_blur=env_float("VR_NRD_EMIS_BLUR", 0.0),
                           method_override=emis_method)
            g.addEdge(n_e + ".filteredDiffuseRadianceHitDist", "ModulateIllumination.emission")
        elif env_bool("VR_NRD_EMISTAA", False):
            # A reprojected temporal AVERAGE of the emissive buffer, which is what an unbiased but
            # on/off signal actually needs -- not a denoiser. Both denoiser routes measured worse
            # (RELAX +6.6%, REBLUR +5.6%): NRD's anti-firefly and history clamping exist to suppress
            # exactly the spikes that ARE the signal here, so they fight it.
            #
            # colorBoxSigma is turned right up because the clamp is the specific thing in the way. On
            # a frame where the reservoir did not pick emission the pixel reads 0, its neighbourhood
            # box collapses to ~0, and a clamped history gets pulled down to 0 with it -- which is
            # why the composite's own TAA leaves emitters as 99% of the worst-flickering pixels no
            # matter how its alpha and sigma are set. Removing the clamp is the point; a long history
            # alone does nothing.
            g.addPass(createPass("TAA", {"alpha": env_float("VR_EMIS_TAA_ALPHA", 0.05),
                                         "colorBoxSigma": env_float("VR_EMIS_TAA_SIGMA", 15.0)}),
                      "EmissiveTAA")
            g.addEdge(restir + ".emissiveColor", "EmissiveTAA.colorIn")
            g.addEdge(gbuffer + ".mvec", "EmissiveTAA.motionVecs")
            g.addEdge("EmissiveTAA.colorOut", "ModulateIllumination.emission")
        else:
            g.addEdge(restir + ".emissiveColor", "ModulateIllumination.emission")
    return "ModulateIllumination.output"


def add_denoiser(g, mode, color, scene, render, display, profile="Balanced", preset="E",
                 upscale_ratio=None,
                 restir="VolumetricReSTIR", gbuffer=None, guides=True,
                 sdk_variant="Current", sr_render_preset="Default", nrd_enabled=True):
    """Wire `color` through denoiser `mode`. Returns the channel holding the result.

        none      passthrough
        oidn      OIDN, CUDA          | full resolution only
        oidncpu   OIDN, CPU           |
        optix     OptiX, temporal     | (fed motion vectors)
        sr        DLSS Super Resolution -- an upscaler that denoises only incidentally (~29%)
        rr        DLSS Ray Reconstruction -- denoises AND upscales in one stage

    `sr` and `rr` need a GBuffer; it is created on demand if one was not passed in. Upscaling is
    implied by render != display, and the DLSS profile must match that ratio.
    """
    upscaling = tuple(render) != tuple(display)

    if mode == "none":
        return color

    if mode in _SIMPLE:
        name, cin, cout = _SIMPLE[mode]
        g.addPass(createPass(name), "Denoiser")
        g.addEdge(color, "Denoiser." + cin)
        if mode == "optix":
            # Motion vectors switch OptiX to its TEMPORAL model; without them it denoises each frame
            # independently. The pass negates them itself (OptiX points forward in time, Falcor
            # points current -> previous).
            gbuffer = gbuffer or add_gbuffer(g, render, jitter=False)
            g.addEdge(gbuffer + ".mvec", "Denoiser.mvec")
        return "Denoiser." + cout

    if mode == "sr":
        gbuffer = gbuffer or add_gbuffer(g, render, jitter=True)
        # sdk_variant picks the DLL, and therefore the network architecture: Current = 310.7.0
        # transformer, LegacyCNN = 3.7.20 convolutional. sr_preset must belong to the same family --
        # a mismatch does not fail, it silently falls back to that DLL's default.
        g.addPass(createPass("DLSSPass", {"enabled": True, "profile": profile,
                                          "sdkVariant": sdk_variant,
                                          "preset": sr_preset(sr_render_preset),
                                          "motionVectorScale": "Relative"}), "DLSSPass")
        g.addEdge(color, "DLSSPass.color")
        g.addEdge(gbuffer + ".depth", "DLSSPass.depth")
        g.addEdge(gbuffer + ".mvec", "DLSSPass.mvec")
        return "DLSSPass.output"

    if mode == "rr":
        gbuffer = gbuffer or add_gbuffer(g, render, jitter=True, upscale=upscaling, ratio=upscale_ratio)
        gd = add_rr_guides(g, scene, gbuffer, restir if guides else None, render=render,
                           upscale=upscaling, ratio=upscale_ratio)
        # DLAA is native; anything else must match the ratio the estimator is rendering at.
        g.addPass(createPass("DLSSDPass", {
            "enabled": True, "profile": profile if upscaling else "DLAA",
            "preset": rr_preset(preset), "isHDR": True, "motionVectorsRelative": True}), "DLSSDPass")
        g.addEdge(color, "DLSSDPass.color")
        g.addEdge(gbuffer + ".linearZ", "DLSSDPass.depth")
        g.addEdge(gbuffer + ".mvec", "DLSSDPass.mvec")
        for ch in ("diffuseAlbedo", "specularAlbedo", "normals", "roughness"):
            g.addEdge(gd + "." + ch, "DLSSDPass." + ch)
        return "DLSSDPass.output"

    if mode == "nrd":
        # NRD v3.1 RELAX. Note this SDK has no SH/SG variants -- NVIDIA's "comparable with DLSS-RR"
        # claim is about SH mode in v4.x, which Falcor's pass cannot drive. Label results as
        # "NRD v3.1 RELAX", not plain "NRD".
        # Jitter is not required by NRD -- it does not upscale, so there is no sub-pixel detail to
        # resolve. It costs temporal variance that NRD then has to filter out, but it also acts as
        # supersampling over the accumulated history, so which way it lands is an empirical question.
        # Measured on the plume: jitter on 6.93e-4, jitter off 6.50e-4 -- 6% worse with it, so off
        # by default. (Ray Reconstruction is the opposite: it upscales, so it needs jitter.)
        #
        # WARNING: that measurement is INVALID and the default is now only a default, not a result.
        # NRDPass passed cameraJitter in UV while NRD wants pixels, so the "jitter on" run was a
        # denoiser told the camera was jittering by 1/1280 of its actual amount -- i.e. told nothing.
        # Of course it scored worse. The units are fixed now; re-measure before quoting the 6%.
        gbuffer = gbuffer or add_gbuffer(g, render, jitter=env_bool("VR_NRD_JITTER", False),
                                         upscale=upscaling, ratio=upscale_ratio)
        # The albedo guide is the demodulation divisor. Reusing DLSSDGuides means the medium-blended
        # albedo NRD divides by is the same one RR is given -- so the two columns see one scene
        # description, not two.
        gd = add_rr_guides(g, scene, gbuffer, restir if guides else None, render=render,
                           upscale=upscaling, ratio=upscale_ratio)

        # VR_NRD_SPLIT=1 denoises the medium and the surfaces separately -- see add_nrd_split for
        # why, and for what it needs from the estimator.
        if env_bool("VR_NRD_SPLIT", False) and guides:
            return add_nrd_split(g, color, scene, render, gbuffer, gd, restir, nrd_enabled=nrd_enabled,
                                 emission=env_bool("VR_NRD_EMISSION", False))

        adapter = "NRDAdapter"
        # VR_NRD_HITDIST=0 ablates the hit-distance guide (constant everywhere). Every guide fed to
        # NRD is worth ablating rather than trusting: the depth guide turned out to be worse than
        # feeding nothing, and only an A/B revealed it.
        # VR_NRD_DEMOD=0 disables demodulation end to end: minReflectance 1.0 makes the divisor 1
        # (albedo is always <= 1), and the graph then skips ModulateIllumination so the albedo is not
        # multiplied back in. Both halves must move together or the round trip is broken.
        demodulate = env_bool("VR_NRD_DEMOD", True)
        # Volumetric demodulation: divide the medium's large-scale structure out of the radiance
        # before NRD filters it, and let ModulateIllumination put it back. Requires the guides.
        voldemod = env_bool("VR_NRD_VOLDEMOD", False) and guides
        props = {"useScatterDistance": env_bool("VR_NRD_HITDIST", True),
                 "useNormalGuide": env_bool("VR_NRD_NORMALS", True),
                 "demodulateVolume": voldemod,
                 "volumeStructureBlur": env_int("VR_NRD_VOLBLUR", 5),
                 "volumeStructureFloor": env_float("VR_NRD_VOLFLOOR", 0.05)}
        if env_bool("VR_NRD_SH", False):
            props["shMode"] = True
            props["shYCoCg"] = env("VR_NRD_METHOD", "").lower().startswith("reblur")
        if not demodulate:
            props["minReflectance"] = 1.0
        if upscaling:
            props.update({"upscale": True, "upscaleRatio": upscale_ratio if upscale_ratio is not None else 0.58})
        elif render is not None:
            props.update({"outputSize": "Fixed", "fixedOutputSize": render})
        # VR_NRD_EMISSION=1 routes directly-visible emitters AROUND the denoiser. NRD demodulates by
        # diffuse albedo, and an emissive bulb has huge radiance with near-zero DIFFUSE albedo, so it
        # takes the full 1/minReflectance amplification -- 100x at the 0.01 floor. The filter then
        # smears that spike across its footprint and re-modulation cannot pull it back, because it
        # multiplies each pixel by its OWN albedo rather than the emitter's. Measured on bistro: a
        # ring 2 px around emitter cores is 14.7x brighter than raw, and the frame gains 10% energy.
        # maxIntensity is NOT the lever -- lowering it to NRD's default made the bloom worse.
        emission = env_bool("VR_NRD_EMISSION", False)
        denoised_in = restir + ".nonEmissiveColor" if emission else color
        g.addPass(createPass("NRDAdapter", props), adapter)
        g.addEdge(denoised_in, adapter + ".color")
        g.addEdge(restir + ".scatterDistance", adapter + ".scatterDistance")
        if voldemod:
            g.addEdge(restir + ".scatterDensity", adapter + ".scatterDensity")
            g.addEdge(restir + ".mediumAlpha", adapter + ".mediumAlpha")
        g.addEdge(gbuffer + ".guideNormalW", adapter + ".guideNormalW")
        g.addEdge(gbuffer + ".specRough", adapter + ".specRough")
        g.addEdge(gd + ".diffuseAlbedo", adapter + ".diffuseAlbedo")
        if env_bool("VR_NRD_SH", False):
            # SH1 is "direction * luminance", so this is required, not a guide that can be omitted --
            # an unconnected lightDir would pack an all-zero SH1, which reads as "no directional
            # information anywhere" and denoises without complaint. NRDAdapter declares the input
            # mandatory in SH mode so a missing edge fails graph compilation instead.
            g.addEdge(restir + ".lightDir", adapter + ".lightDir")

        # The plugin registers as "NRD", not "NRDPass". worldSpaceMotion must be False: Falcor
        # defaults it True (inverting NRD's own default) and GBufferRaster has no mvecW at all, so we
        # feed 2D screen-space vectors. Getting this wrong ghosts rather than errors.
        # maxIntensity luminance-clamps radiance before denoising; the 1000 default would discard
        # energy from a demodulated HDR signal, so raise it and record the value.
        # enabled=False makes NRDPass blit input->output unchanged, which turns the whole graph into
        # an identity test of the demodulate/re-modulate round trip -- independent of the denoiser.
        # VR_NRD_SH=1 selects NRD v4's spherical-harmonics mode: the adapter emits an SH0/SH1 pair
        # instead of packed radiance, RELAX_DIFFUSE_SH denoises it, and NRDPass resolves it back to
        # radiance internally -- so everything downstream is unchanged.
        #
        # VR_NRD_SH_RESOLVE picks the resolve semantics, and the choice is not cosmetic. Both scenes
        # use an ISOTROPIC phase function (g=0), for which outgoing radiance is the uniform spherical
        # average -- the DC term. NRD's own resolve instead evaluates a cosine lobe about a surface
        # normal, which a medium does not have. "dc" is the physically defensible one; "cosine" is
        # NVIDIA's intended usage, kept so the difference can be measured rather than argued.
        sh = env_bool("VR_NRD_SH", False)
        # VR_NRD_METHOD overrides the denoiser outright, for the v4 additions that take the same IO
        # as RelaxDiffuse (ReblurDiffuse, and the SH variants). Denoisers with different inputs --
        # SIGMA wants penumbra, Reference wants a raw signal, the occlusion variants want a hit
        # distance -- are reachable from NRDPass but are NOT wired into this graph.
        method = env("VR_NRD_METHOD", "RelaxDiffuseSh" if sh else "RelaxDiffuse")
        nrd_props = {"method": method,
                     "worldSpaceMotion": False, "maxIntensity": env_float("VR_NRD_MAXINT", 100000.0), "enabled": nrd_enabled}
        if sh:
            nrd_props["shResolveMode"] = env("VR_NRD_SH_RESOLVE", "Dc")
        # VR_NRD_VALIDATION=1 renders NRD's own debug overlay (viewZ, normals, motion vectors,
        # history length) to a 'validation' output. It is the instrument for questions like "is the
        # depth guide sane" -- which took a capture-and-analyse cycle to answer without it.
        validation = env_bool("VR_NRD_VALIDATION", False)
        if validation:
            nrd_props["enableValidation"] = True
        g.addPass(createPass("NRD", nrd_props), "NRD")
        if validation:
            g.markOutput("NRD.validation")
        if sh:
            g.addEdge(adapter + ".diffuseSh0", "NRD.diffuseSh0")
            g.addEdge(adapter + ".diffuseSh1", "NRD.diffuseSh1")
        else:
            g.addEdge(adapter + ".diffuseRadianceHitDist", "NRD.diffuseRadianceHitDist")
        g.addEdge(adapter + ".normWRoughnessMaterialID", "NRD.normWRoughnessMaterialID")
        # viewZ must be the GEOMETRIC surface depth, not the estimator's scatter-weighted linearZ.
        # RELAX uses depth for reprojection and edge-stopping, so a depth that moves with smoke
        # density makes it reject the wrong neighbours. Measured on the plume: feeding the estimator's
        # scatter depth scored 8.54e-4, feeding nothing at all scored 6.93e-4 -- i.e. the scatter
        # depth was worse than no depth. Falcor's own reference graph (scripts/PathTracerNRD.py)
        # feeds GBufferRT.linearZ for the same reason. (Ray Reconstruction is the opposite case: it
        # is volumetric-aware and does want the scatter depth.)
        # VIEW Z. This is not the free choice it looks like.
        #
        # The G-buffer's linearZ is the geometric surface depth, which is the right answer for a
        # SURFACE renderer -- RELAX uses depth to reproject and to reject neighbours, and a depth that
        # moves with smoke density makes it reject the wrong ones.
        #
        # But plume has essentially no rasterizable geometry: it is lit by an environment map over a
        # bare plane, so GBufferRaster writes NOTHING and linearZ is measured to be ALL ZEROS. A zero
        # depth reconstructs every pixel to the camera origin, so NRD's reprojection is degenerate and
        # its history never accumulates -- which makes every temporal setting inert. Measured on the
        # animated plume: phiLuminance 2 vs 32, maxAccumulatedFrameNum 30 vs 1, and surface vs volume
        # motion vectors were ALL byte-identical.
        #
        # An earlier note here recorded that the estimator's scatter depth scored worse than "nothing"
        # (8.54e-4 vs 6.93e-4). That comparison was made on a STATIC scene, i.e. in the regime where
        # NRD declines to filter at all, so it did not measure depth quality and should not be relied
        # on. VR_NRD_VIEWZ exists to re-settle it now that the scene moves.
        viewz = env("VR_NRD_VIEWZ", "gbuffer").lower()
        if viewz == "restir":
            g.addEdge(restir + ".linearZ", "NRD.viewZ")
        else:
            g.addEdge(gbuffer + ".linearZ", "NRD.viewZ")

        # Motion vectors. The G-buffer's are SURFACE motion only, so in principle an animated medium
        # would reproject as if it were static, and the estimator's own mvec is the volume-aware one:
        # it advects the sample point back through the velocity grid (GenerateFeatures.cs.slang).
        #
        # VR_NRD_VOLMV=1 selects it, but it defaults OFF because the difference is currently
        # UNMEASURABLE and therefore unverified. Neither scene can exercise it: load_plume passes
        # hasVelocity=False and a single VDB frame ("Static plume..."), and the advection is guarded by
        # `hasVelocity && hasAnimation`. With a pinned camera both sources are camera-only, i.e. ~0,
        # and the two wirings measured BYTE-IDENTICAL (3.282e-03 either way, plume at frame 200).
        # Default left on the measured path rather than the plausible one -- switching a default on an
        # untested hypothesis is how a guess later gets read as a validated fix. Revisit with a scene
        # that has a velocity grid, or a moving camera.
        #
        # NOTE viewZ deliberately stays on the G-buffer -- see the note above; depth and motion want
        # different things here, which is unintuitive enough to be worth stating twice.
        if env_bool("VR_NRD_VOLMV", False):
            # An mvec output the estimator is not configured to write is an EMPTY texture, which NRD
            # reads as "nothing moved anywhere" -- the worst possible failure here, because it looks
            # like a working temporal denoiser that simply never reprojects. The pass defaults to
            # MotionVecMode::Off, so requesting the volume-aware path without Deterministic mode is
            # always a mistake; refuse rather than measure it.
            # Read it back off the pass rather than trusting the caller: VolumetricReSTIR::getProperties
            # reports the mode it actually settled on, which is not always the one requested (an
            # unrecognised value warns and leaves the previous mode in place).
            try:
                mode = g.get_pass(restir).properties.get("mMotionVecMode")
            except Exception as e:
                raise RuntimeError("VR_NRD_VOLMV=1: could not read '%s' properties: %s" % (restir, e))
            if mode != "Deterministic":
                raise RuntimeError(
                    "VR_NRD_VOLMV=1 needs the estimator writing volume-aware motion vectors, but "
                    "'%s' reports mMotionVecMode=%r (need 'Deterministic'). An unwritten mvec output "
                    "would hand NRD an empty texture, i.e. a scene where nothing ever moves."
                    % (restir, mode))
            g.addEdge(restir + ".mvec", "NRD.mvec")
        else:
            g.addEdge(gbuffer + ".mvec", "NRD.mvec")

        if not demodulate:
            # Nothing was divided out, so nothing may be multiplied back.
            return "NRD.filteredDiffuseRadianceHitDist"

        # Re-modulation is the caller's job; Falcor already ships the pass for it.
        g.addPass(createPass("ModulateIllumination"), "ModulateIllumination")
        g.addEdge("NRD.filteredDiffuseRadianceHitDist", "ModulateIllumination.diffuseRadiance")
        # With demodulation on the multiplier MUST be the adapter's own divisor, or the round trip
        # is only as good as two sites agreeing on a formula by hand. With it off, keep the original
        # edge so a disabled feature means an unchanged graph.
        if voldemod:
            g.addEdge(adapter + ".demodDivisor", "ModulateIllumination.diffuseReflectance")
        else:
            g.addEdge(gd + ".diffuseAlbedo", "ModulateIllumination.diffuseReflectance")
        # Additive, and never filtered. emissive + denoised(non-emissive) reconstructs the original.
        if emission:
            g.addEdge(restir + ".emissiveColor", "ModulateIllumination.emission")

        # VR_NRD_TAA=1 appends temporal anti-aliasing. This is not a denoiser setting -- it addresses
        # a DIFFERENT artifact that no amount of denoising can remove.
        #
        # A pixel is a point sample. Thin geometry (window grilles, the string lights, railings) is
        # narrower than a pixel or straddles its boundary, so as the camera moves sub-pixel amounts
        # the sample lands on the bar in one frame and misses it in the next. The renderer is not
        # uncertain about that pixel -- it is confidently sampling a different thing each frame -- so
        # NRD cannot fix it, and measurement puts the residual flicker exactly on that geometry.
        #
        # TAA fixes it by jittering the camera sub-pixel per frame and accumulating with
        # reprojection, so each pixel converges to the area average. That is why jitter must be ON
        # for this to do anything at all: without it every frame samples the identical sub-pixel
        # location and there is no extra coverage to accumulate.
        #
        # This is also what makes NRD comparable to Ray Reconstruction. RR does denoising AND the
        # temporal AA resolve in one learned pass; NRD is denoise-only, so without this the two are
        # not the same kind of thing. Measured on bistro under camera motion, RR was 52% steadier.
        if env_bool("VR_NRD_TAA", False):
            g.addPass(createPass("TAA", taa_props()), "TAA")
            g.addEdge("ModulateIllumination.output", "TAA.colorIn")
            g.addEdge(gbuffer + ".mvec", "TAA.motionVecs")
            return "TAA.colorOut"
        return "ModulateIllumination.output"

    raise ValueError("unknown denoiser '%s' (have: %s)" % (mode, ", ".join(DENOISERS)))


def add_tonemapper(g, src, exposure=0.0, name="ToneMapper"):
    """Auto-exposure stays OFF so two configurations are tonemapped identically and remain
    comparable; the trade is that each scene needs its own fixed compensation.

    Bistro is a night exterior and needs +8 EV -- 256x. At 0 it renders essentially black with only
    the emitters surviving, which is indistinguishable from broken lighting and cost a long hunt
    through the estimator, the params and the render scale before the tonemapper was suspected.
    """
    # Linear operator, not the default filmic curve. An S-curve compresses highlights, which is
    # exactly where two denoiser configurations differ most -- so a filmic tonemap hides the thing
    # these images exist to show. Exposure compensation still applies, so a night exterior is
    # viewable; the mapping above it is just a straight scale.
    op = env("VR_TONEMAP_OP", "Linear")
    g.addPass(createPass("ToneMapper", {"autoExposure": False, "exposureCompensation": exposure,
                                        "operator": op}), name)
    g.addEdge(src, name + ".src")
    return name + ".dst"


def pin_clock(framerate=None):
    """Make animation advance per FRAME rather than per wall-clock second.

    Without this, `time` is driven by real elapsed time, so the scene state at "frame 200" depends on
    how fast the machine happened to run -- which is how a Bistro capture ended up pointing at the
    night sky in one run and the street in another. Pinning the framerate makes
    `time = frame / framerate`, so frame N is the same scene state in every run and on every machine.

    Returns the framerate actually set, or None if pinning was skipped (VR_FRAMERATE=0).
    """
    fps = env_int("VR_FRAMERATE", 60) if framerate is None else framerate
    if fps <= 0:
        return None
    m.clock.framerate = fps
    m.clock.time = 0.0
    return fps


def hold_volume_frame(index, restir="VolumetricReSTIR", graph=None):
    """Pin an animated GVDB sequence to one frame.

    REQUIRED alongside the clock hold, not instead of it. The sequence is advanced by
    `Scene::update` once per RENDERED frame and wraps modulo numFrames -- it never consults the
    clock, so `timeScale = 0` stops scene time and leaves the volume marching on. A per-frame
    reference built without this would accumulate over a different volume state every sample and
    never converge, while looking perfectly healthy.

    `mVolumeAnimationSelectedFrameId` is 0-based into the LOADED sequence (not the on-disk frame
    number); -1 means "play". Returns the index pinned.
    """
    g = graph or m.activeGraph
    g.get_pass(restir).set_properties({"mVolumeAnimationSelectedFrameId": int(index)})
    return int(index)


def advance_and_hold(frame, accum="Accum", graph=None, volume_frames=None, restir="VolumetricReSTIR"):
    """Run the animation forward to `frame`, then hold that exact scene state.

    This is what makes a PER-FRAME reference possible, and a per-frame reference is what any fair
    comparison of a temporal denoiser needs. The two existing options are both unusable for that:

      * freezing from frame 0 (`VR_FREEZE_ANIM=1`) converges, but only ever to the t=0 state, and it
        removes the frame-to-frame variation that NRD's variance estimator is built on -- with a
        temporally stable input RELAX concludes the signal is clean and stops filtering (see
        Source/RenderPasses/NRDPass/README.md). Measured on plume: with the scene frozen,
        diffusePhiLuminance 2 and 32 produce numerically identical output (1.6e-14 apart).
      * not freezing at all never converges: an accumulation averages a different scene state every
        frame, so the error GROWS with sample count (measured 4.7e-4 at 500-vs-3000 samples,
        8.1e-4 at 3000-vs-30000) -- the signature of a moving target, not a noisy one.

    Holding at frame N gives both: the denoised run reaches frame N through N frames of real
    animation, and the reference converges on the state it finds there.

    Does NOT use `scene.animated = False`, which is a bigger hammer than it looks -- it stops the scene
    update that the emissive LightCollection and the volume rely on, leaving a frame lit only by
    directly-visible emitters, which reads as a lighting bug.

    Does NOT use `clock.pause()` either, though that is the obvious choice and was tried first.
    `Clock::tick` only calls `step()` when not paused, and `step()` is what advances `mFrames` --
    while FrameCapture and `clock.exitFrame` both trigger off `getGlobalClock().getFrame()`. Pausing
    therefore freezes the exact counter the capture is waiting for: the run accumulates forever and
    writes nothing, with no error anywhere.

    Instead: reach frame N with the framerate pinned (deterministic), then drop to real-time mode with
    `timeScale = 0`. In `step()`, a pinned framerate makes time a pure function of the frame count and
    ignores `timeScale`, so the two settings have to be changed together -- with `framerate = 0` the
    time becomes `timer.delta() * scale + time.now`, which at `scale = 0` holds at the value just
    reached. Scene time stops, the frame counter keeps running, capture still fires.

    Resetting the accumulator is not optional: everything summed while the scene was still moving is
    an average over different states and would bias the reference towards the approach frames.
    """
    for _ in range(max(0, frame)):
        m.renderFrame()
    m.clock.timeScale = 0.0
    m.clock.framerate = 0

    # An animated VDB sequence ignores the clock entirely -- see hold_volume_frame. Pin it to
    # whichever frame the run actually reached.
    #
    # The arithmetic is NOT `frame % numFrames`. addGVDBVolumeSequence starts the index at
    # numFrames - 1 and advanceVolumeAnimation PRE-increments `(id + 1) % numFrames`, so after N
    # rendered frames the index is (N - 1) % numFrames. Getting this off by one silently references a
    # DIFFERENT volume state than the run being scored -- which inflates every row uniformly and
    # looks like "all the denoisers are bad" rather than like a bug.
    if volume_frames:
        n = int(volume_frames)
        hold_volume_frame((max(0, frame) - 1) % n if frame > 0 else (n - 1), restir=restir, graph=graph)

    # Guard the failure this function was rewritten to avoid: if the hold ever stops the frame
    # counter again, FrameCapture never fires and the run writes NOTHING while reporting success.
    # One frame is enough to tell -- and it costs one frame.
    _before = m.clock.frame
    m.renderFrame()
    if m.clock.frame == _before:
        raise RuntimeError(
            "advance_and_hold: the frame counter is frozen at %d after holding, so FrameCapture and "
            "clock.exitFrame will never trigger and this run would produce no output. Hold time via "
            "timeScale/framerate, not clock.pause()." % _before)
    _held = m.clock.time
    m.renderFrame()
    if m.clock.time != _held:
        raise RuntimeError(
            "advance_and_hold: scene time is still advancing (%r -> %r) after holding, so the "
            "accumulation would average different scene states and never converge."
            % (_held, m.clock.time))
    if accum:
        try:
            (graph or m.activeGraph).get_pass(accum).reset()
        except Exception as e:
            # Loud: a silently un-reset accumulator yields a reference that looks plausible and is
            # wrong, which is the single most expensive kind of error in this project.
            raise RuntimeError("advance_and_hold: could not reset accumulator '%s': %s" % (accum, e))


def add_accumulator(g, src, name="Accum", precision="SingleCompensated"):
    """Accumulate for a ground-truth reference.

    Kahan (`SingleCompensated`) rather than the pass's `Single` default: summing thousands of HDR
    samples containing fireflies in naive single precision loses the low-order contributions once the
    running sum is large, which biases exactly the pixels a denoiser is judged on. Costs one extra
    buffer. NOTE the existing plume reference was made with `Single`; that is fine, because MSE is
    only ever compared within a scene, but do not mix the two for one scene.
    """
    g.addPass(createPass("AccumulatePass", {"enabled": True, "precisionMode": precision}), name)
    g.addEdge(src, name + ".input")
    return name + ".output"


def capture(graph, frame, out_dir, tag, exit_after=False):
    """Capture one frame, if VR_CAPTURE_FRAME (or the caller) asks for it.

    `exit_after` quits once the capture has flushed, for unattended runs. The 60-frame margin is not
    optional: Texture::captureToFile writes asynchronously, and quitting on the capture frame itself
    truncates the file.
    """
    if frame <= 0:
        return
    os.makedirs(out_dir, exist_ok=True)
    m.frameCapture.outputDir = out_dir
    m.frameCapture.baseFilename = tag
    m.frameCapture.addFrames(graph, [frame])
    if exit_after:
        m.clock.exitFrame = frame + 60
