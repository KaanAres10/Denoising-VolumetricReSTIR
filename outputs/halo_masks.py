# Capture the estimator's mediumAlpha (smoke coverage) at the three stop poses of record_look.py's
# stop-and-go orbit, to bin the halo metrics by coverage (m_halo_alpha.py, m_halo_fringe.py,
# m_halo_band.py). Geometry only -- the same for every denoiser configuration.
#
# Run with the same VR_SCENE / VR_DISPLAY as the recordings (960x540). Writes outputs/halo_masks for
# bistro and outputs/halo_masks_<scene> otherwise; the metric scripts read HALO_MASKS=<dir>.
import os, math
LOOK = r"C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\run_bistro_relax.py"
__file__ = LOOK
exec(compile(open(LOOK).read(), LOOK, "exec"), globals())
m.activeGraph.markOutput(restir + ".mediumAlpha")
vr.pin_clock(30)
OUT = r"C:/research/Denoising-VolumetricReSTIR/outputs/" + ("halo_masks" if SCENE == "bistro" else "halo_masks_" + SCENE)
os.makedirs(OUT, exist_ok=True)
FRAMES, STOPS = 300, 3
stop_pos = sorted(int(round(j * FRAMES / (STOPS + 1))) - 1 for j in range(1, STOPS + 1))  # 74, 149, 224
# record_look.py's orbit centres -- keep in sync.
cx, cy, cz = {"bistro": (-11.0, 6.025879, 0.0), "plume": (0.0, 1.66, 0.0), "explosion": (-0.2, 14.8, -0.6)}[SCENE]
cam = m.scene.camera
p = cam.position
radius = math.sqrt((p.x - cx) ** 2 + (p.z - cz) ** 2)
a0 = math.atan2(p.z - cz, p.x - cx)
step = math.radians(-180.0) / (FRAMES - 1)
m.frameCapture.outputDir = OUT
m.frameCapture.baseFilename = "alpha"
m.frameCapture.addFrames(m.activeGraph, [20 * (k + 1) - 1 for k in range(len(stop_pos))])
for k, i in enumerate(stop_pos):
    a = a0 + step * i
    cam.position = float3(cx + radius * math.cos(a), p.y, cz + radius * math.sin(a))
    cam.target = float3(cx, cy, cz)
    for _ in range(20):
        m.renderFrame()
    print("[alpha] stop %d at orbit position %d" % (k + 1, i))
m.clock.exitFrame = 20 * len(stop_pos) + 40
for _ in range(40):
    m.renderFrame()
