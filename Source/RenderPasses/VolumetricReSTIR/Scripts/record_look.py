# Record exactly what a Look window shows, for a video that matches the live side-by-side comparison
# (rr_compare_windows.cmd). The orbit videos do not: they render at 1080p and are shrunk for the
# side-by-side, which averages noise away, and they follow the orbit path aimed at a different point.
#
# This builds the graph by running run_bistro_relax.py itself -- the same code the windows run, so the
# two cannot drift -- then pins the clock, warms up at the windows' starting pose and captures
# TAA_LDR.colorOut, the image a Look window displays, while orbiting the plume (or holding still).
#
#   VR_OUT_DIR=<dir> (required)   VR_TAG=look            capture folder and filename prefix
#   VR_RECORD_FRAMES=300          frames of camera motion (10 s at the pinned 30 fps); stops add to it
#   VR_RECORD_WARM=60             frames rendered first, so RR's history has converged
#   VR_RECORD_ORBIT_DEG=-180      bistro/plume: sweep the camera this far around the plume while recording,
#                                 on capture_orbit.py's authored orbit (same centre, radius from the
#                                 windows' starting position, constant height). 0 holds it still.
#   VR_RECORD_STOPS=0             stop-and-go: halt the orbit this many times, evenly along the path...
#   VR_RECORD_STOP_S=5            ...for this many seconds each, then carry on at the same speed. Shows
#                                 how each denoiser settles when the camera stops and what it smears
#                                 when motion resumes.
#   VR_FRAMERATE=30               the pinned clock
#   plus everything run_bistro_relax.py reads: VR_DENOISER, VR_SDK, VR_PRESET, VR_DISPLAY (the window
#   size to match -- rr_compare_windows.cmd opens 960x540), ...
import os
import sys

_HERE = r"C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts"
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    pass
LOOK = os.path.join(_HERE, "run_bistro_relax.py")
# The Look script finds vr_graph next to itself through __file__.
__file__ = LOOK
exec(compile(open(LOOK).read(), LOOK, "exec"), globals())

FRAMES = vr.env_int("VR_RECORD_FRAMES", 300)
WARM = vr.env_int("VR_RECORD_WARM", 60)
OUT_DIR = os.environ["VR_OUT_DIR"]
TAG = vr.env("VR_TAG", "look")

# Pinned, so frame N is the same scene state in both recordings however fast each one ran. The live
# windows run on the wall clock; on this view that measured 0.11 vs 0.12/255 of frame-to-frame change,
# i.e. it does not change what is seen.
FPS = vr.pin_clock(vr.env_int("VR_FRAMERATE", 30)) or 30

# One orbit position per captured frame. Stops repeat a position; the orbit itself is spread over the
# FRAMES moving frames either way, so it runs at the same speed with or without them.
STOPS = vr.env_int("VR_RECORD_STOPS", 0)
STOP_FRAMES = int(round(vr.env_float("VR_RECORD_STOP_S", 5.0) * FPS))
_bounds = {int(round(j * FRAMES / (STOPS + 1))) for j in range(1, STOPS + 1)}
SCHEDULE = []
for i in range(FRAMES):
    SCHEDULE.append(i)
    if i + 1 in _bounds:
        SCHEDULE += [i] * STOP_FRAMES

os.makedirs(OUT_DIR, exist_ok=True)  # FrameCapture does not create it
m.frameCapture.outputDir = OUT_DIR
m.frameCapture.baseFilename = TAG
m.frameCapture.addFrames(m.activeGraph, [WARM + k for k in range(len(SCHEDULE))])

# The orbit of capture_orbit.py: about the plume, NOT about the camera's own target -- bistro's target
# sits 0.95 units from the camera, so orbiting it spins the camera on the spot. Radius and height come
# from the starting position, so the sweep begins where the windows open. On the plume scene the centre
# is the fire115 volume's axis (its world bounds are x,z -0.83..0.83, y 0.03..3.29).
import math
ORBIT_CENTERS = {"bistro": (-11.0, 6.025879, 0.0), "plume": (0.0, 1.66, 0.0),
                  "explosion": (-0.2, 14.8, -0.6)}
ORBIT_DEG = vr.env_float("VR_RECORD_ORBIT_DEG", -180.0) if SCENE in ORBIT_CENTERS else 0.0
ORBIT_CENTER = ORBIT_CENTERS.get(SCENE, (0.0, 0.0, 0.0))
cam = m.scene.camera
_cx, _cy, _cz = ORBIT_CENTER
_p = cam.position
_radius = math.sqrt((_p.x - _cx) ** 2 + (_p.z - _cz) ** 2)
_a0 = math.atan2(_p.z - _cz, _p.x - _cx)
_step = math.radians(ORBIT_DEG) / max(1, FRAMES - 1)


def place(i):
    if ORBIT_DEG == 0.0:
        return  # held at the windows' starting pose, target and all
    a = _a0 + _step * i
    cam.position = float3(_cx + _radius * math.cos(a), _p.y, _cz + _radius * math.sin(a))
    cam.target = float3(_cx, _cy, _cz)


print("[record] %s  %d frames after %d warm-up, %s%s -> %s"
      % (TAG, len(SCHEDULE), WARM, ("orbit %.0f deg around the plume" % ORBIT_DEG) if ORBIT_DEG else "camera held at the starting pose",
         (", %d stops of %d frames" % (STOPS, STOP_FRAMES)) if STOPS and ORBIT_DEG else "", OUT_DIR))
sys.stdout.flush()

# Warm up at the first pose, record while moving, then hold: Texture::captureToFile writes
# asynchronously, so quitting on the last captured frame would truncate it (as in capture_orbit.py).
m.clock.exitFrame = WARM + len(SCHEDULE) + 60
place(0)
for _ in range(WARM):
    m.renderFrame()
for i in SCHEDULE:
    place(i)
    m.renderFrame()
for _ in range(60):
    m.renderFrame()
