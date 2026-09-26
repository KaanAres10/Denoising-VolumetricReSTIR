# Time the ESTIMATOR ALONE on the bistro orbit, for comparing engines -- the Falcor 8.0 / 9.0 twin of
# legacy/Scripts/_time_raw_legacy.py (the falcor4-legacy build). Everything that decides the cost is
# held to that script:
#
#   graph      VolumetricReSTIR -> ToneMapper (Linear, fixed +8 EV, no auto-exposure). No G-buffer, TAA,
#              guides or denoiser, so nothing but the estimator differs between engines.
#   estimator  surface scene + emissive lights, no environment lights, M threshold 10, 1 initial and
#              1 final light sample, spatial and temporal reuse on.
#   scene      Bistro + smoke-plume-2, scene AND camera animation frozen (legacy sets
#              m.scene.animated = False; without it the new engines re-update the light collection
#              every frame, which cost 3-6 ms and made the first 4.x-vs-8.0 comparison unfair).
#   path       the -180 degree orbit about (-11, 6.025879, 0), placed by loop index, 30 warm-up frames
#              at the start pose, then FRAMES timed frames.
#   timing     Python wall clock around each renderFrame(), no capture in the timed loop.
#
# One known difference: legacy also loads skylight-morn.exr at intensity 0. Environment lighting is off
# in both, so it adds no light; it is left out here as in the earlier 4.x-vs-8.0 measurement.
#
#   VR_FRAMES=300          VR_RESULT=<path>  writes "<engine>,n,mean,median,p95,min,max" + <path>.csv
#   VR_ENGINE=v9           label for the result line
#   VR_VERIFY=1 VR_OUT_DIR=<dir>   capture ONE frame (orbit pose 150) and exit, instead of timing --
#              run it on every engine before trusting a timing: two builds must render the same image.
#   VR_PASS_TIMES=1        per-pass GPU time from Falcor's profiler -> <VR_RESULT>.passes.json. The
#              timer queries cost time themselves, so do it in separate runs from the wall-clock ones.
import math
import os
import sys
import time

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

W, H = 1920, 1080
FRAMES = vr.env_int("VR_FRAMES", 300)
WARM = 30
CENTER = (-11.0, 6.025879, 0.0)
ENGINE = vr.env("VR_ENGINE", "new")

scene = vr.load_bistro()
m.scene.animated = False
m.scene.camera.animated = False

g = RenderGraph("time_raw")
restir = vr.add_restir(g, scene, render=(W, H),
                       mParams={"mInitialLightSamples": 1, "mFinalLightSamples": 1,
                                # VR_NO_TEMPORAL / VR_NO_SPATIAL, as the legacy script reads them.
                                "mEnableTemporalReuse": not vr.env_bool("VR_NO_TEMPORAL", False),
                                "mEnableSpatialReuse": not vr.env_bool("VR_NO_SPATIAL", False)})
out = vr.add_tonemapper(g, restir + ".accumulated_color", exposure=8.0)
g.markOutput(out)
m.addGraph(g)
m.resizeSwapChain(W, H)
m.ui = False
vr.pin_clock(30)

cam = m.scene.camera
cx, cy, cz = CENTER
p = cam.position
radius = math.sqrt((p.x - cx) ** 2 + (p.z - cz) ** 2)
y = p.y
a0 = math.atan2(p.z - cz, p.x - cx)
orbit = -180.0 * math.pi / 180.0


def place(i):
    a = a0 + (i / float(FRAMES - 1)) * orbit
    cam.position = float3(cx + radius * math.cos(a), y, cz + radius * math.sin(a))
    cam.target = float3(cx, cy, cz)


place(0)
for _ in range(WARM):
    m.renderFrame()

if vr.env_bool("VR_VERIFY", False):
    # Same pose and frame count as the legacy script's verify branch.
    place(150)
    for _ in range(8):
        m.renderFrame()
    f = int(m.clock.frame) + 1
    # exit_after sets the exit 60 frames after the capture, once the asynchronous write has landed.
    # Mogwai only acts on it after the script RETURNS, so render past it and fall off the end -- a
    # loop that waits for the exit never ends.
    vr.capture(g, f, os.environ["VR_OUT_DIR"], "verify_" + ENGINE, exit_after=True)
    for _ in range(64):
        m.renderFrame()
else:
    PASS_TIMES = vr.env_bool("VR_PASS_TIMES", False)
    if PASS_TIMES:
        m.profiler.enabled = True
        m.profiler.start_capture(FRAMES + 16)

    times = []
    for i in range(FRAMES):
        place(i)
        t0 = time.perf_counter()
        m.renderFrame()
        times.append((time.perf_counter() - t0) * 1000.0)

    s = sorted(times)
    mean = sum(times) / len(times)
    print("[time_raw] %s  mean %.2f ms  median %.2f  p95 %.2f  min %.2f  max %.2f"
          % (ENGINE, mean, s[len(s) // 2], s[int(len(s) * 0.95)], s[0], s[-1]))
    _out = os.environ.get("VR_RESULT")
    if _out:
        with open(_out, "w") as fh:
            fh.write("%s,%d,%.4f,%.4f,%.4f,%.4f,%.4f\n"
                     % (ENGINE, len(times), mean, s[len(s) // 2], s[int(len(s) * 0.95)], s[0], s[-1]))
        with open(_out + ".csv", "w") as fh:
            fh.write("frame,ms\n")
            for k, ms in enumerate(times):
                fh.write("%d,%.4f\n" % (k, ms))
        if PASS_TIMES:
            import json
            cap = m.profiler.end_capture()
            lanes = {}
            for name, lane in (cap or {}).get("events", {}).items():
                rec = sorted(r for r in lane["records"] if r == r)
                if rec:
                    lanes[name] = {"median": rec[len(rec) // 2], "mean": lane["stats"]["mean"], "n": len(rec)}
            with open(_out + ".passes.json", "w") as fh:
                json.dump(lanes, fh, indent=1)
    sys.stdout.flush()
    # Mogwai keeps running once the script returns; exit explicitly (see capture_orbit.py).
    m.clock.exitFrame = int(m.clock.frame) + 2
    m.renderFrame()
    m.renderFrame()
