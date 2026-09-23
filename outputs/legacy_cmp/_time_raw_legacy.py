# Tracked copy of legacy/Scripts/_time_raw_legacy.py (untracked in the falcor4-legacy worktree). Run it
# from there with the legacy Mogwai; outputs/legacy_cmp/time_batch.ps1 does.
# Falcor 4 fork: time the ESTIMATOR ALONE on the same bistro orbit, the same way the v8 script does
# (Python wall-clock around renderFrame, no capture). Only the VolumetricReSTIR pass is in the graph,
# so no tonemapper or denoiser cost is included on either side.
from falcor import *
import math, os, sys, time

W, H = 1920, 1080
FRAMES = int(os.environ.get("VR_FRAMES", "300"))
WARM = 30
D = "C:/research/Denoising-VolumetricReSTIR/VolumetricReSTIRData"
CENTER = (-11.0, 6.025879, 0.0)

def render_graph():
    g = RenderGraph("time_raw_legacy")
    loadRenderPassLibrary("VolumetricReSTIR.dll")
    _surf = not os.environ.get("VR_NO_SURFACE")
    _emis = not os.environ.get("VR_NO_EMISSIVE")
    _ls = int(os.environ.get("VR_LIGHT_SAMPLES", "1"))
    vrestir = createPass("VolumetricReSTIR", {
        "mParams": VolumetricReSTIRParams(
            mUseSurfaceScene=_surf, mUseEmissiveLights=_emis,
            mUseEnvironmentLights=False, mTemporalReuseMThreshold=10.0,
            mInitialLightSamples=_ls, mFinalLightSamples=_ls,
            mEnableSpatialReuse=not os.environ.get("VR_NO_SPATIAL"),
            mEnableTemporalReuse=not os.environ.get("VR_NO_TEMPORAL"))})
    loadRenderPassLibrary("ToneMapper.dll")
    # Same +8 EV as the v8 script, for the same reason: without it the window is black except the
    # emitters. Linear operator and auto-exposure OFF so both builds apply the identical transform.
    tonemap = createPass("ToneMapper", {
        "operator": ToneMapOp.Linear,
        "autoExposure": False,
        "exposureCompensation": 8.0,
    })
    g.addPass(vrestir, "VolumetricReSTIR")
    g.addPass(tonemap, "ToneMapper")
    g.addEdge("VolumetricReSTIR.accumulated_color", "ToneMapper.src")
    g.markOutput("ToneMapper.dst")
    return g

m.loadScene(D + "/Bistro_5_1/BistroExterior.fbx")
m.scene.setEnvMap(D + "/skylight-morn.exr")
m.scene.setEnvMapRotation(float3(0, 72.5, 0))
m.scene.setEnvMapIntensity(0)
if not os.environ.get("VR_NO_VOLUME"):
    m.addGVDBVolume(sigma_a=float3(10,10,10), sigma_s=float3(80,80,80), g=0.0,
                    dataFile=D + "/smoke-plume-2", numMips=4)
m.scene.animated = False
m.scene.camera.animated = False
m.scene.camera.position = float3(-15.149291, 8.352362, -8.399609)
m.scene.camera.target   = float3(-14.742913, 8.025879, -7.546224)
m.scene.camera.up       = float3(0.004061, 0.999961, 0.007782)

m.addGraph(render_graph())
m.resizeSwapChain(W, H)
m.ui = False
fc.ui = False
vc.ui = False
t.pause(); t.frame = 0; t.framerate = 30

# Per-pass GPU timings, so the two builds can be compared pass by pass rather than only on total
# frame time. Same event names as the 8.0 port registers via FALCOR_PROFILE.
# Falcor 4's profiler keys events by their full nesting path joined with '#', and looks names up
# without matching -- a bare "Spatial Reuse" silently creates a new, never-triggered event and records
# zeros. The estimator pass is the graph node "VolumetricReSTIR".
_pp = os.environ.get("VR_PASSTIME")
if _pp:
    _root = "#onFrameRender#RenderGraphExe::execute()#VolumetricReSTIR"
    tc.capturePassTime(_pp + "_estimator.csv", _root)
    for _n in ("Generate Features", "Generate Samples", "Temporal Reuse", "Spatial Reuse", "Copy resource", "Final Shading"):
        tc.capturePassTime(_pp + "_" + _n.replace(" ", "_") + ".csv", _root + "#" + _n)

cx, cy, cz = CENTER
# Falcor 4's float3 binding does not expose .x/.y/.z to Python -- the fork's own capture scripts
# parse the repr for exactly this reason. Attribute access kills the process (0xC000013A).
import re
_f = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
def f3(v):
    n = _f.findall(str(v))
    if len(n) < 3: raise ValueError("cannot parse float3 from %r" % (v,))
    return float(n[0]), float(n[1]), float(n[2])
sx, sy, sz = f3(m.scene.camera.position)
radius = math.sqrt((sx - cx) ** 2 + (sz - cz) ** 2)
y_off = sy - cy
a0 = math.atan2(sz - cz, sx - cx)
orbit = -180.0 * math.pi / 180.0

def place(i):
    a = a0 + (i / float(FRAMES - 1)) * orbit
    m.scene.camera.position = float3(cx + radius * math.cos(a), cy + y_off, cz + radius * math.sin(a))
    m.scene.camera.target = float3(cx, cy, cz)

place(0)
for _ in range(WARM):
    renderFrame()

if os.environ.get("VR_VERIFY"):
    # Same graph as the timing path; capture one frame so "is the volume actually rendering?"
    # is answered by the image rather than assumed.
    place(150)
    for _ in range(8):
        renderFrame()
    fc.outputDir = os.environ["VR_OUT_DIR"]
    fc.baseFilename = "verify_legacy"
    fc.capture()
    for _ in range(4):
        renderFrame()
    print("[verify] captured to", os.environ["VR_OUT_DIR"])
    sys.stdout.flush()
    exit()

times = []
for i in range(FRAMES):
    place(i)
    t0 = time.perf_counter()
    renderFrame()
    times.append((time.perf_counter() - t0) * 1000.0)

s = sorted(times)
mean = sum(times) / len(times)
_out = os.environ.get("VR_RESULT")
if _out:
    with open(_out, "w") as fh:
        fh.write("legacy,%d,%.4f,%.4f,%.4f,%.4f,%.4f\n"
                 % (len(times), mean, s[len(s)//2], s[int(len(s)*0.95)], s[0], s[-1]))
    with open(_out + ".csv", "w") as fh:
        fh.write("frame,ms\n")
        for _k, _ms in enumerate(times):
            fh.write("%d,%.4f\n" % (_k, _ms))

exit()
