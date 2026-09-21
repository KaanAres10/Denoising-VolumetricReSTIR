"""Capture an ingested dataset to a PNG sequence for encoding to mp4.

  VR_DATASET=firePlume VR_STRIDE=1 Mogwai.exe --script capture_sequence.py

Transform and density come from the baked header, not from hand-tuned constants.
VR_NUM_FRAMES lets a partially ingested window be played back without editing the manifest.
"""
import os
import sys
from pathlib import Path
from falcor import *

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import vdb_pipeline as vp

REPO = SCRIPTS.parents[3]
DATA_DIR = REPO / "VolumetricReSTIRData"
NAME = os.environ.get("VR_DATASET", "firePlume")

ds = vp.get_dataset(NAME)
if os.environ.get("VR_NUM_FRAMES"):
    # A true override: also drops any playback_frames cap, so the VRAM ceiling can be probed.
    ds = dict(ds, num_frames=int(os.environ["VR_NUM_FRAMES"]), playback_frames=None)
frames = vp.playback_frame_numbers(ds)
out_dir = DATA_DIR / NAME
prefix = ds["file_pattern"].split("{")[0]

# Placement is derived from the middle frame, not the first: V1 measured that GVDB rebases every
# frame's origin to zero while the extent grows, so anchoring on frame 0 makes a growing volume
# expand away from one corner.
pframe = vp.placement_frame(frames)
header = vp.read_baked_header(out_dir / f"{prefix}{pframe:04d}.bin")
scale, trans = vp.derive_placement(header.extent, ds["placement"]["centre"],
                                   ds["placement"]["target_height"])
density = vp.derive_density_scale(ds["medium"]["density_scale_ref"], scale)
print(f"[{NAME}] placement frame={pframe} extent={header.extent} scale={scale:.6g} "
      f"density={density:.6g} emission={header.has_emission} frames={len(frames)}")

m.loadScene(str(DATA_DIR / "default.obj"))
m.scene.setEnvMap(str(DATA_DIR / "hansaplatz_8k.hdr"))

med = ds["medium"]
m.scene.addGVDBVolumeSequence(
    sigma_a=float3(*med["sigma_a"]), sigma_s=float3(*med["sigma_s"]), g=med["g"],
    dataFilePrefix=str(out_dir / prefix), numberFixedLength=4,
    startFrame=frames[0], numFrames=len(frames), numMips=ds["num_mips"],
    densityScale=density, hasVelocity=ds["has_velocity"], hasEmission=ds["has_emission"],
    LeScale=med["le_scale"], temperatureCutoff=med["temperature_cutoff"],
    temperatureScale=med["temperature_scale"],
    worldTranslation=float3(*trans), worldRotation=float3(0, 0, 0), worldScaling=scale)

m.scene.camera.position = float3(1.977354, 2.411630, 2.242076)
m.scene.camera.target = float3(1.366226, 2.220231, 1.474033)
m.scene.camera.up = float3(0.0, 1.0, 0.0)


def render_graph():
    g = RenderGraph("Volume dataset " + NAME)
    vr = createPass("VolumetricReSTIR", {'mParams': {
        'mEnableTemporalReuse': True, 'mEnableSpatialReuse': True,
        'mUseEnvironmentLights': True, 'mUseEmissiveLights': False}})
    g.addPass(vr, "VolumetricReSTIR")
    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 0.0})
    g.addPass(tm, "ToneMapper")
    g.addEdge("VolumetricReSTIR.accumulated_color", "ToneMapper.src")
    g.markOutput("ToneMapper.dst")
    g.markOutput("VolumetricReSTIR.mvec")
    return g


m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True

# The sequence advances ONE volume frame per RENDERED frame (Scene::update ->
# advanceVolumeAnimation), so a rendered frame maps 1:1 onto an animation frame and the capture
# list must be consecutive. Accumulating N rendered frames per animation frame would need the
# animation pinned via mVolumeAnimationSelectedFrameId, which a Mogwai script cannot step between
# captures; that is the route to clean stills and is deliberately not attempted here.
# Each captured frame is therefore what temporal ReSTIR reuse actually produces in motion, which
# is the honest input for denoiser work.
STRIDE = int(os.environ.get("VR_STRIDE", "1"))
out = REPO / "shots" / NAME
os.makedirs(out, exist_ok=True)
# Clear previous captures: numbering restarts at 1, so a shorter re-run would leave the tail of
# the previous one behind and encode_video would splice two runs into one video.
for stale in list(out.glob("*.png")) + list(out.glob("*.exr")):
    stale.unlink()
m.frameCapture.outputDir = str(out)
m.frameCapture.baseFilename = "frame"
capture_at = [1 + i * STRIDE for i in range(len(frames))]
m.frameCapture.addFrames(m.activeGraph, capture_at)
print(f"[{NAME}] capturing {len(capture_at)} frames -> {out}")
# Margin: captureToFile writes asynchronously, so quitting on the last capture truncates it.
m.clock.exitFrame = capture_at[-1] + 60
