# Capture the authored orbit as a frame sequence, for video.
#
# Same camera path as every measurement in Source/RenderPasses/NRDPass/STATE.md and as the published
# page: a -180 degree sweep about (-11, 6.025879, 0) at constant height, always looking at that point
# (Bistro; plume orbits its own centre, see ORBIT_CENTER).
# The centre is NOT the camera's target -- Bistro's target sits 0.95 units from the camera, so orbiting
# around it spins the camera on the spot, which disoccludes violently and scores every denoiser ~4x
# worse. That was a property of the path, not of rotation.
#
# TIMING IS PINNED, which is the part that makes this reproducible. Without it Falcor drives `time`
# from real elapsed seconds, so the scene state at "frame 200" depends on how fast the machine ran --
# how a Bistro capture once ended up pointing at the night sky in one run and the street in another.
# vr.pin_clock(FPS) makes time = frame / framerate, so frame N is the same state on every run, on every
# machine, and at every resolution. Encode the result at the same FPS and the video is correct in wall
# time as well.
#
#   VR_SCENE=bistro|plume     VR_DISPLAY=1920x1080    VR_FRAMES=300    VR_FRAMERATE=30
#   VR_WARM=30                frames rendered at the start pose before capturing, so the temporal
#                             denoisers are converged when frame 0 is written. Without it the first
#                             seconds of every clip are a different algorithm than the rest.
#   VR_ORBIT_DEG=-180         VR_OUT_DIR=<where to write>   VR_TAG=<filename prefix>
#   VR_PRESET=E               rr only: D | E | F (F = RR2)  VR_SDK=Current | Previous310_7 (DLSS DLLs)
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

vr.bind(m)

RENDER = vr.env_size("VR_DISPLAY", (1920, 1080))
FRAMES = vr.env_int("VR_FRAMES", 300)
FPS = vr.env_int("VR_FRAMERATE", 30)
WARM = vr.env_int("VR_WARM", 30)
ORBIT_DEGREES = vr.env_float("VR_ORBIT_DEG", -180.0)
OUT_DIR = os.environ["VR_OUT_DIR"]
TAG = vr.env("VR_TAG", "orbit")
SCENE = vr.env("VR_SCENE", "bistro").lower()
# The orbit centre is per scene. Bistro's is the street point above. Plume's is where the authored close-up
# (vr_graph.load_plume) looks at the plume: its view ray passes within 0.15 of the medium's vertical axis
# at y = 1.83, so orbiting (0, 1.83, 0) keeps that framing at radius ~3. Until 2026-09-26 plume used
# Bistro's centre too, which swung the camera round a point 11 units away (radius 13.2) with the plume
# small and off-centre in frame; plume orbit captures from before then are of that view.
# VR_ORBIT_CENTER=x,y,z overrides it.
_ORBIT_CENTERS = {"bistro": (-11.0, 6.025879, 0.0), "plume": (0.0, 1.83, 0.0)}
_center_env = vr.env("VR_ORBIT_CENTER", "")
if _center_env:
    ORBIT_CENTER = tuple(float(v) for v in _center_env.split(","))
else:
    ORBIT_CENTER = _ORBIT_CENTERS.get(SCENE, _ORBIT_CENTERS["bistro"])
MODE = vr.env("VR_DENOISER", "nrd").lower()
# Defaults are what every orbit before 310.9.1 was captured with: preset E on the DLL beside the
# executable. That DLL is now 310.9.1, so VR_SDK=Previous310_7 is what reproduces those captures.
PRESET = vr.env("VR_PRESET", "E")
SDK_VARIANT = vr.env("VR_SDK", "Current")

g = RenderGraph(SCENE + "_orbit")
scene = vr.load_scene(SCENE)
restir = vr.add_restir(g, scene, render=RENDER, guides=True, mOutputDepth=True,
                       mMotionVecMode="Deterministic")
# Only the SINGLE-PASS denoisers get a G-buffer built here. OIDN creates none at all, so wiring TAA's
# motion vectors to GBufferRaster died with "Can't find render pass 'GBufferRaster'".
#
# Everything else must build its own, because add_denoiser picks the jitter each denoiser needs and
# `gbuffer or add_gbuffer(...)` means passing one in silently overrides that choice. Ray
# Reconstruction asks for jitter=True -- it reconstructs sub-pixel detail and needs the camera to
# jitter -- while the NRD path asks for jitter=False. Handing every mode one non-jittered G-buffer
# quietly denied RR its jitter and made it a different configuration from every earlier RR run in
# this project. Fixed by only pre-building where nothing else will.
_NEEDS_GBUFFER = ("oidn", "oidncpu", "none")
gbuf = vr.add_gbuffer(g, RENDER, jitter=False) if MODE in _NEEDS_GBUFFER else None
out = vr.add_denoiser(g, MODE, restir + ".accumulated_color", scene, RENDER, RENDER,
                      restir=restir, gbuffer=gbuf, guides=True, preset=PRESET, sdk_variant=SDK_VARIANT)
# Whoever built it, the pass is named GBufferRaster; TAA's motion vectors come from there.
gbuf = gbuf or "GBufferRaster"
tm = vr.add_tonemapper(g, out, exposure=scene.get("exposure", 0.0))
if vr.env_bool("VR_TAA_LDR", True):
    g.addPass(createPass("TAA", vr.taa_props()), "TAA_LDR")
    g.addEdge(tm, "TAA_LDR.colorIn")
    # WHICH motion vectors TAA reprojects with. GBufferRaster's are RASTERIZED, so at a pixel the
    # smoke covers they describe the WALL BEHIND it -- the plume is not in the G-buffer at all. The
    # estimator's deterministic mvec is computed at `expectedT`, the expected scattering depth inside
    # the medium, so it is the only one that reprojects the plume itself.
    #
    # This is not academic: with the surface mvec, TAA ERASES the plume from the undenoised image
    # (plume-region p95 0.4367 -> 0.3608 on the bistro orbit) because sparse volumetric samples get
    # reprojected onto wall history. The denoised paths survive it -- their plume is already a solid
    # mass that TAA's colour clamp holds -- which is why this only became visible on the raw panel.
    # ON by default on measurement (bistro orbit, 300 frames at 1080p, surface -> volume mvec):
    #   RELAX-SH   s=32 9.34 -> 9.24   plume 14.06 -> 13.60
    #   REBLUR-SH  s=32 9.35 -> 9.28   plume 13.90 -> 13.54
    #   DLSS RR    s=32 9.32 -> 8.96   plume 15.84 -> 14.54
    #   OptiX      s=32 11.65 -> 10.70 plume 19.94 -> 17.28
    #   raw ReSTIR s=32 9.64 -> 9.20   plume 15.66 -> 13.85
    # Every path improves, most in the plume, which is where the parallax error lives. Plume detail
    # drops 2-4% (raw 17%) -- that is TAA finally ACCUMULATING instead of leaving smeared
    # high-frequency residue, not detail being lost. The switch is live, not dead: 45-61% of pixels
    # differ, max delta 255. VR_TAA_VOLMV=0 restores the G-buffer mvec.
    _taa_mv = gbuf + ".mvec"
    if vr.env_bool("VR_TAA_VOLMV", True):
        _mode = g.get_pass(restir).properties.get("mMotionVecMode")
        if _mode != "Deterministic":
            raise RuntimeError(
                "VR_TAA_VOLMV=1 needs the estimator writing volume-aware motion vectors, but "
                "'%s' reports mMotionVecMode=%r (need 'Deterministic'). An unwritten mvec output "
                "would hand TAA an empty texture, i.e. a scene where nothing ever moves." % (restir, _mode))
        _taa_mv = restir + ".mvec"
    g.addEdge(_taa_mv, "TAA_LDR.motionVecs")
    tm = "TAA_LDR.colorOut"

# Only the shipped image is marked. Marking the raw HDR buffers as well means the capture can pick one
# of them, and bistro is a night exterior needing the tonemapper's +8 EV -- an HDR buffer written
# straight out looks black with a few coloured bulbs, which reads as a broken render and is not one.
# VR_CAPTURE_RAW=1 captures the estimator's UNDENOISED HDR output instead of the shipped image,
# with no denoiser, tonemapper or TAA in the path. That is what isolates the estimator when comparing
# two builds: everything downstream is removed, and the instability metric normalises by mean
# brightness, so the two builds' different exposure handling cancels.
if vr.env_bool("VR_CAPTURE_RAW", False):
    tm = restir + ".accumulated_color"
# VR_CAPTURE_DENOISED=1 captures the DENOISER's HDR output, before the tonemapper and TAA.
# Needed to compare against another build whose tonemapper differs: the LDR metric otherwise
# measures the transfer curve (Linear + autoExposure vs a fixed +8 EV) as much as the denoiser.
if vr.env_bool("VR_CAPTURE_DENOISED", False):
    tm = out
g.markOutput(tm)
m.addGraph(g)
m.resizeSwapChain(RENDER[0], RENDER[1])
m.ui = False

vr.pin_clock(FPS)

cam = m.scene.camera
_cx, _cy, _cz = ORBIT_CENTER
_p = cam.position
_radius = math.sqrt((_p.x - _cx) ** 2 + (_p.z - _cz) ** 2)
_y = _p.y
_a0 = math.atan2(_p.z - _cz, _p.x - _cx)
_step = (ORBIT_DEGREES * math.pi / 180.0) / max(1, FRAMES - 1)


def place(i):
    a = _a0 + _step * i
    cam.position = float3(_cx + _radius * math.cos(a), _y, _cz + _radius * math.sin(a))
    cam.target = float3(_cx, _cy, _cz)


os.makedirs(OUT_DIR, exist_ok=True)

# VR_TIME=1 measures frame cost and captures NOTHING.
#
# These two cannot share a run. Every captured frame here is a ~2.5 MB 1080p PNG read back from the
# GPU and written asynchronously; the readback stalls the pipeline and the writes back up, so an FPS
# measured while capturing is the disk's number, not the renderer's. Hence two passes, the same split
# the reference orbit script makes with MODE = timing | frames | both -- and "both" is the one that
# quietly produces a wrong answer.
#
# What this measures is WALL CLOCK END TO END: CPU submit + GPU + present, an upper bound rather than
# a GPU-only figure. It is directly comparable BETWEEN the configurations below, since they run the
# identical path at the identical resolution, which is what a denoiser comparison needs.
#
# VR_PASS_TIMES=1 (with VR_TIME=1) adds Falcor's profiler, which splits that frame per render pass on
# the CPU and the GPU. This used to be written off as unreachable ("Mogwai exposes no device to
# Python"), but Mogwai binds it directly as m.profiler, and RenderGraphExe wraps every pass in an event
# named after it. It is what can see a denoiser's own cost: a 0.3 ms difference inside a ~120 ms frame
# is below the run-to-run spread of the wall clock. Opt-in, because the timer queries are themselves a
# cost the wall-clock column should not carry.
TIMING = vr.env_bool("VR_TIME", False)
PASS_TIMES = TIMING and vr.env_bool("VR_PASS_TIMES", False)
if not TIMING:
    m.frameCapture.outputDir = OUT_DIR
    m.frameCapture.baseFilename = TAG
    # Frame indices are absolute, so the captured range starts after the warm-up.
    m.frameCapture.addFrames(g, [WARM + k for k in range(FRAMES)])

print("[orbit] scene=%s denoiser=%s method=%s preset=%s sdk=%s  %dx%d  %d frames @ %d fps  warm=%d"
      % (SCENE, MODE, vr.env("VR_NRD_METHOD", "RelaxDiffuseSh"), PRESET, SDK_VARIANT,
         RENDER[0], RENDER[1], FRAMES, FPS, WARM))
print("[orbit] r=%.3f about (%.2f,%.2f,%.2f), %.4f rad/frame -> %s"
      % (_radius, _cx, _cy, _cz, _step, OUT_DIR))
sys.stdout.flush()

# Warm-up at the START pose, so the temporal denoisers are converged before frame 0 is written.
place(0)
for _ in range(WARM):
    m.renderFrame()

import time

if PASS_TIMES:
    # After the warm-up, so NGX feature creation and shader compiles are not in the capture.
    m.profiler.enabled = True
    m.profiler.start_capture(FRAMES + 16)

times = []
# Clock guard. The camera is placed by THIS loop's counter, but frames are captured by the Mogwai
# clock's absolute frame number (addFrames above). Those only agree while the clock advances exactly
# one frame per renderFrame(). In one 300-frame RR run on Falcor 9.0 it did not: the clock held still
# for ~31 iterations near the end, so every capture from that point on landed in the 60-frame tail
# after the loop -- all at the FINAL pose. No error, no warning, 300 unique PNGs; it scored as a 10%
# denoiser regression until the frames were looked at. A re-run was byte-identical up to the stall and
# clean after it, so it was an event, not the engine. Cause not established.
#
# A stalled run is not rescued by fixing the poses, either: the temporal denoisers would still have
# seen repeated frames, so the history differs from a clean run. The only safe outcome is to say so.
try:
    os.remove(os.path.join(OUT_DIR, "CLOCK_STALL.txt"))  # a marker from an earlier run into this dir
except OSError:
    pass
# Checked RELATIVE to the first reading, not against WARM: read before renderFrame() the clock reports
# the frame it last rendered, so loop 0 sees WARM - 1 (the log's "frame 0 (clock frame 29)" is normal).
_clock_f0 = int(m.clock.frame)
_clock_bad = []
for i in range(FRAMES):
    _f = int(m.clock.frame)
    if _f != _clock_f0 + i:
        _clock_bad.append((i, _f, _clock_f0 + i))
    place(i)
    t0 = time.perf_counter()
    m.renderFrame()
    times.append((time.perf_counter() - t0) * 1000.0)
    if i % 50 == 0:
        print("[orbit] frame %d/%d  (clock frame %d)" % (i, FRAMES - 1, _f))
        sys.stdout.flush()

if _clock_bad:
    _i, _got, _want = _clock_bad[0]
    _msg = ("CLOCK STALL: the Mogwai clock stopped tracking the orbit at loop %d (clock %d, expected %d); "
            "%d of %d frames affected. Captures from there on are at the WRONG POSE and the temporal "
            "history is not that of a clean run -- discard this capture and re-run it."
            % (_i, _got, _want, len(_clock_bad), FRAMES))
    print("[orbit] " + _msg)
    sys.stdout.flush()
    # A file next to the frames, so a batch that only counts PNGs cannot miss it.
    with open(os.path.join(OUT_DIR, "CLOCK_STALL.txt"), "w") as fh:
        fh.write(_msg + "\n")
        for _i, _got, _want in _clock_bad:
            fh.write("loop %d: clock %d, expected %d\n" % (_i, _got, _want))

if TIMING:
    # Per-frame CSV, so the distribution can be inspected rather than trusting a single mean -- the
    # orbit is not uniform work, and a mean hides the cost of the frames facing the plume.
    csv = os.path.join(OUT_DIR, "%s_frame_times.csv" % TAG)
    with open(csv, "w") as fh:
        fh.write("frame,ms\n")
        for k, ms in enumerate(times):
            fh.write("%d,%.4f\n" % (k, ms))
    s = sorted(times)
    mean = sum(times) / len(times)
    print("[time] %s  mean %.2f ms (%.1f fps)  median %.2f  p95 %.2f  min %.2f  max %.2f  -> %s"
          % (TAG, mean, 1000.0 / mean, s[len(s) // 2], s[int(len(s) * 0.95)], s[0], s[-1], csv))
    if PASS_TIMES:
        import json
        cap = m.profiler.end_capture()
        lanes = {}
        for name, lane in (cap or {}).get("events", {}).items():
            # The first records can predate the GPU timestamps resolving; the median ignores them.
            rec = sorted(r for r in lane["records"] if r == r)
            if rec:
                lanes[name] = {"mean": lane["stats"]["mean"], "std_dev": lane["stats"]["std_dev"],
                               "median": rec[len(rec) // 2], "p95": rec[int(len(rec) * 0.95)],
                               "n": len(rec)}
        js = os.path.join(OUT_DIR, "%s_pass_times.json" % TAG)
        with open(js, "w") as fh:
            json.dump({"frame_count": (cap or {}).get("frame_count", 0), "lanes": lanes}, fh, indent=1)
        for name in sorted(lanes):
            if name.endswith("/gpu_time") and ("DLSS" in name or "Denoiser" in name or "NRD" in name):
                print("[pass] %s  median %.3f ms  mean %.3f  p95 %.3f"
                      % (name, lanes[name]["median"], lanes[name]["mean"], lanes[name]["p95"]))
        print("[pass] %d lanes -> %s" % (len(lanes), js))
    # MUST exit explicitly. Mogwai's main loop keeps running once the script returns, so without this
    # the timing pass finishes its ~1 minute of work and then idle-spins forever -- which looked
    # exactly like a slow renderer (11 minutes wall against 152 s of CPU) and was not one. The capture
    # branch below already exits via clock.exitFrame; this branch had nothing.
    m.clock.exitFrame = WARM + FRAMES + 2
    m.renderFrame()
else:
    # Texture::captureToFile writes ASYNCHRONOUSLY. Quitting on the final captured frame truncates it,
    # so hold for a margin before exiting -- the same reason vr.capture() adds 60.
    m.clock.exitFrame = WARM + FRAMES + 60
    for _ in range(60):
        m.renderFrame()
    print("[orbit] done, %d frames in %s" % (FRAMES, OUT_DIR))
sys.stdout.flush()
