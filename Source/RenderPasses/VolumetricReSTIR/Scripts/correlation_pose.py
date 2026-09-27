# ReSTIR's pixel correlation at one still pose: separately seeded chains of raw frames, for the
# decorrelation study (docs/superpowers/specs/2026-09-27-restir-mcmc-decorrelation-design.md).
# outputs/decorr/m_corr.py computes the covariance metrics from what this writes.
#
# Each chain starts from a history reset seeded through the pass's `frameSeed` property, warms up, then
# captures frames `spacing` apart; chains own disjoint frame-count ranges (correlation_schedule.py says
# why that matters). An optional burst captures consecutive frames for the temporal autocorrelation.
#
#   VR_SCENE=bistro|plume|explosion|emerald|bunny|wdas|fireplume|dust   (vr_graph.SCENES)
#   VR_MODE=restir|reference   ReSTIR chains, or a brute-force path-traced reference of the same pose
#   VR_DISPLAY=1920x1080       render size
#   VR_CHAINS=10  VR_PER_CHAIN=10  VR_SPACING=33  VR_WARM=<default max(256, 4 * M cap)>
#   VR_BURST=0                 frames of the consecutive burst (0 = none)
#   VR_SEED_BASE=100000  VR_SEED_STRIDE=<default: smallest multiple of 10000 above a chain>
#   VR_IDS=1                   also capture the sampleIdentity output
#   VR_DENOISER=none|optix|oidn|nrd|rr   capture this denoiser's HDR output instead (capture_orbit's
#                              pipeline; VR_NRD_METHOD etc. as there). Its history is not reset between
#                              chains: the warm-up (>= 256 frames) outlasts any denoiser's history.
#   VR_NO_TEMPORAL / VR_NO_SPATIAL   switch a reuse stage off; the vr_graph knobs (VR_MTHRESH,
#                              VR_SR_RADIUS, VR_SR_COUNT, VR_SR_ROUNDS, VR_PHASE_G) apply as usual
#   VR_FRAMES=8192 VR_SPP=16   reference mode: accumulated frames and samples per pixel per frame
#   VR_OUT_DIR, VR_TAG         where, and the file prefix
#
# Writes <TAG>.VolumetricReSTIR.accumulated_color.<frame>.exr (+ .sampleIdentity), and
# <TAG>.schedule.json describing the chains; reference mode writes <TAG>.Accum.output.<frame>.exr at
# FRAMES/2 and FRAMES (two averages give independent halves for the reference's own noise).
import json
import math
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
from correlation_schedule import build_schedule

vr.bind(m)

NAME = vr.env("VR_SCENE", "bistro")
MODE = vr.env("VR_MODE", "restir").lower()
REFERENCE = MODE == "reference"
W, H = vr.env_size("VR_DISPLAY", (1920, 1080))
OUT_DIR = os.environ["VR_OUT_DIR"]
TAG = vr.env("VR_TAG", MODE)

scene = vr.load_scene(NAME)
# A still pose needs a still scene: Bistro's FBX animates its lanterns (reference_pose.py freezes it the
# same way), and the other scenes have nothing to animate.
m.scene.animated = False
m.scene.camera.animated = False

params = {"mInitialLightSamples": 1, "mFinalLightSamples": 1}
if REFERENCE:
    params["mBaselineSamplePerPixel"] = vr.env_int("VR_SPP", 16)
else:
    params["mEnableTemporalReuse"] = not vr.env_bool("VR_NO_TEMPORAL", False)
    params["mEnableSpatialReuse"] = not vr.env_bool("VR_NO_SPATIAL", False)

DENOISER = vr.env("VR_DENOISER", "none").lower()
g = RenderGraph("correlation_pose")
channel = "VolumetricReSTIR.accumulated_color"
if REFERENCE:
    restir = vr.add_restir(g, scene, render=(W, H), reference=True, mParams=params)
    g.markOutput(vr.add_accumulator(g, restir + ".accumulated_color"))
elif DENOISER != "none":
    # capture_orbit.py's pipeline up to the denoiser (its Look config comes from the same VR_NRD_* /
    # VR_OPTIX_* variables), capturing the denoiser's HDR output: what correlated error survives it.
    restir = vr.add_restir(g, scene, render=(W, H), guides=True, mOutputDepth=True,
                           mMotionVecMode="Deterministic", mParams=params)
    gbuf = vr.add_gbuffer(g, (W, H), jitter=False) if DENOISER in ("oidn", "oidncpu") else None
    channel = vr.add_denoiser(g, DENOISER, restir + ".accumulated_color", scene, (W, H), (W, H),
                              restir=restir, gbuffer=gbuf, guides=True, preset=vr.env("VR_PRESET", "E"),
                              sdk_variant=vr.env("VR_SDK", "Current"))
    g.markOutput(channel)
else:
    restir = vr.add_restir(g, scene, render=(W, H), mParams=params)
    g.markOutput(restir + ".accumulated_color")
    if vr.env_bool("VR_IDS", False):
        g.markOutput(restir + ".sampleIdentity")
m.addGraph(g)
m.resizeSwapChain(W, H)
m.ui = False
vr.pin_clock(30)

if NAME == "bistro":
    # reference_pose.py's pose: orbit pose 150 of time_raw.py (the verify frame), so Bistro captures
    # score against the existing references (outputs/pending_9p/forkref/cap/v9sa_ref).
    cx, cy, cz = (-11.0, 6.025879, 0.0)
    cam = m.scene.camera
    p = cam.position
    radius = math.sqrt((p.x - cx) ** 2 + (p.z - cz) ** 2)
    a = math.atan2(p.z - cz, p.x - cx) + (150 / float(300 - 1)) * (-math.pi)
    cam.position = float3(cx + radius * math.cos(a), p.y, cz + radius * math.sin(a))
    cam.target = float3(cx, cy, cz)

m.renderFrame()  # the camera settles
f0 = int(m.clock.frame)
os.makedirs(OUT_DIR, exist_ok=True)
m.frameCapture.outputDir = OUT_DIR
m.frameCapture.baseFilename = TAG
env = {k: v for k, v in sorted(os.environ.items()) if k.startswith("VR_")}

if REFERENCE:
    frames = vr.env_int("VR_FRAMES", 8192)
    captures = [f0 + frames // 2 - 1, f0 + frames - 1]  # accumulated counts FRAMES/2 and FRAMES
    m.frameCapture.addFrames(g, captures)
    with open(os.path.join(OUT_DIR, TAG + ".schedule.json"), "w") as fh:
        json.dump({"scene": NAME, "mode": MODE, "display": [W, H], "first": f0,
                   "reference_frames": captures, "accumulated": [frames // 2, frames], "env": env}, fh, indent=1)
    print("[correlation_pose] %s reference: %d frames x %d spp" % (NAME, frames, params["mBaselineSamplePerPixel"]))
    m.clock.exitFrame = captures[-1] + 60
    for _ in range(frames + 64):
        m.renderFrame()
else:
    mcap = vr.env_float("VR_MTHRESH", scene.get("params", {}).get("mTemporalReuseMThreshold", 4.0))
    warm = vr.env_int("VR_WARM", max(256, int(math.ceil(4 * mcap))))
    stride = vr.env_int("VR_SEED_STRIDE", 0) or None
    s = build_schedule(f0=f0, chains=vr.env_int("VR_CHAINS", 10), per_chain=vr.env_int("VR_PER_CHAIN", 10),
                       warm=warm, spacing=vr.env_int("VR_SPACING", 33), burst=vr.env_int("VR_BURST", 0),
                       seed_base=vr.env_int("VR_SEED_BASE", 100000), seed_stride=stride)
    runs = s["chains"] + ([s["burst"]] if s["burst"] else [])
    captures = [f for run in runs for f in run["frames"]]
    m.frameCapture.addFrames(g, captures)
    with open(os.path.join(OUT_DIR, TAG + ".schedule.json"), "w") as fh:
        json.dump(dict(s, scene=NAME, mode=MODE, display=[W, H], warm=warm, mcap=mcap,
                       spacing=vr.env_int("VR_SPACING", 33), channel=channel, denoiser=DENOISER, env=env),
                  fh, indent=1)
    print("[correlation_pose] %s: %d chains x %d captures, warm %d, spacing %d, burst %d, %d frames, seeds %s"
          % (NAME, len(s["chains"]), len(s["chains"][0]["frames"]), warm, vr.env_int("VR_SPACING", 33),
             vr.env_int("VR_BURST", 0), s["total"], [r["seed"] for r in runs]))
    m.clock.exitFrame = captures[-1] + 60
    for run in runs:
        g.get_pass("VolumetricReSTIR").set_properties({"frameSeed": run["seed"]})
        for _ in range(run["length"]):
            m.renderFrame()
    for _ in range(64):
        m.renderFrame()
