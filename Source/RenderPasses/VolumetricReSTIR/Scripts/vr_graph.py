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
        gbuffer = gbuffer or add_gbuffer(g, render, jitter=env_bool("VR_NRD_JITTER", False),
                                         upscale=upscaling, ratio=upscale_ratio)
        # The albedo guide is the demodulation divisor. Reusing DLSSDGuides means the medium-blended
        # albedo NRD divides by is the same one RR is given -- so the two columns see one scene
        # description, not two.
        gd = add_rr_guides(g, scene, gbuffer, restir if guides else None, render=render,
                           upscale=upscaling, ratio=upscale_ratio)

        adapter = "NRDAdapter"
        # VR_NRD_HITDIST=0 ablates the hit-distance guide (constant everywhere). Every guide fed to
        # NRD is worth ablating rather than trusting: the depth guide turned out to be worse than
        # feeding nothing, and only an A/B revealed it.
        # VR_NRD_DEMOD=0 disables demodulation end to end: minReflectance 1.0 makes the divisor 1
        # (albedo is always <= 1), and the graph then skips ModulateIllumination so the albedo is not
        # multiplied back in. Both halves must move together or the round trip is broken.
        demodulate = env_bool("VR_NRD_DEMOD", True)
        props = {"useScatterDistance": env_bool("VR_NRD_HITDIST", True),
                 "useNormalGuide": env_bool("VR_NRD_NORMALS", True)}
        if env_bool("VR_NRD_SH", False):
            props["shMode"] = True
        if not demodulate:
            props["minReflectance"] = 1.0
        if upscaling:
            props.update({"upscale": True, "upscaleRatio": upscale_ratio if upscale_ratio is not None else 0.58})
        elif render is not None:
            props.update({"outputSize": "Fixed", "fixedOutputSize": render})
        g.addPass(createPass("NRDAdapter", props), adapter)
        g.addEdge(color, adapter + ".color")
        g.addEdge(restir + ".scatterDistance", adapter + ".scatterDistance")
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
        nrd_props = {"method": "RelaxDiffuseSh" if sh else "RelaxDiffuse",
                     "worldSpaceMotion": False, "maxIntensity": 100000.0, "enabled": nrd_enabled}
        if sh:
            nrd_props["shResolveMode"] = env("VR_NRD_SH_RESOLVE", "Dc")
        g.addPass(createPass("NRD", nrd_props), "NRD")
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
        g.addEdge(gd + ".diffuseAlbedo", "ModulateIllumination.diffuseReflectance")
        return "ModulateIllumination.output"

    raise ValueError("unknown denoiser '%s' (have: %s)" % (mode, ", ".join(DENOISERS)))


def add_tonemapper(g, src, exposure=0.0, name="ToneMapper"):
    """Auto-exposure stays OFF so two configurations are tonemapped identically and remain
    comparable; the trade is that each scene needs its own fixed compensation.

    Bistro is a night exterior and needs +8 EV -- 256x. At 0 it renders essentially black with only
    the emitters surviving, which is indistinguishable from broken lighting and cost a long hunt
    through the estimator, the params and the render scale before the tonemapper was suspected.
    """
    g.addPass(createPass("ToneMapper", {"autoExposure": False, "exposureCompensation": exposure}), name)
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
