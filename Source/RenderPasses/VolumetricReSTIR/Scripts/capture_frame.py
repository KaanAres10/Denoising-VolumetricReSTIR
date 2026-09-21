"""Render ONE frame of a dataset and exit, holding only that frame's volume in VRAM.

  VR_DATASET=dustShockwave VR_FRAME=60 VR_ACC=32 Mogwai.exe --script capture_frame.py

Why this exists: addGVDBVolumeSequence uploads every frame's GPU resources up front and nothing
ever frees them, so a 16-frame dustShockwave window already sits at 7.7 GB of an 8.1 GB card
(~380 MiB/frame) and 32 frames dies. Nothing actually needs the other frames --
volumeDesc.usePrevGridForReproj is false, so the shaders' useLastFrameGrid is always false and only
the current frame's grid is ever sampled. Loading one frame per process costs
baseline + ~380 MiB instead of baseline + N x 380 MiB.

TRADE-OFF, and it is not a small one: each process starts cold, so there is no temporal ReSTIR
reuse carried across animation frames. VR_ACC accumulates within a frame instead, which converges
each frame toward a clean still. Good for a long beauty render; NOT the same data as the animated
path if you are measuring how a denoiser behaves over time.

Driven by render_sequence_streamed.py, which also fixes up the output names for encoding.
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
NAME = os.environ.get("VR_DATASET", "dustShockwave")
FRAME = int(os.environ["VR_FRAME"])
ACC = int(os.environ.get("VR_ACC", "32"))
OUT = Path(os.environ.get("VR_OUT", str(REPO / "shots" / (NAME + "_streamed"))))

ds = vp.get_dataset(NAME)
out_dir = DATA_DIR / NAME
prefix = ds["file_pattern"].split("{")[0]

# Same placement the animated path uses, so streamed and sequence renders are comparable.
extent = vp.imported_extent(ds)
scale, trans = vp.derive_placement(extent, ds["placement"]["centre"],
                                   ds["placement"]["target_height"])
density = vp.derive_density_scale(ds["medium"]["density_scale_ref"], scale)

m.loadScene(str(DATA_DIR / "default.obj"))
m.scene.setEnvMap(str(DATA_DIR / "hansaplatz_8k.hdr"))

med = ds["medium"]
m.scene.addGVDBVolume(
    sigma_a=float3(*med["sigma_a"]), sigma_s=float3(*med["sigma_s"]), g=med["g"],
    dataFile=str(out_dir / f"{prefix}{FRAME:04d}"),
    numMips=ds["num_mips"], densityScale=density,
    hasVelocity=ds["has_velocity"], hasEmission=ds["has_emission"],
    LeScale=med["le_scale"], temperatureCutoff=med["temperature_cutoff"],
    temperatureScale=med["temperature_scale"],
    worldTranslation=float3(*trans), worldRotation=float3(0, 0, 0), worldScaling=scale)

m.scene.camera.position = float3(1.977354, 2.411630, 2.242076)
m.scene.camera.target = float3(1.366226, 2.220231, 1.474033)
m.scene.camera.up = float3(0.0, 1.0, 0.0)


def render_graph():
    g = RenderGraph("streamed " + NAME)
    vr = createPass("VolumetricReSTIR", {'mParams': {
        'mEnableTemporalReuse': True, 'mEnableSpatialReuse': True,
        'mUseEnvironmentLights': True, 'mUseEmissiveLights': False}})
    g.addPass(vr, "VolumetricReSTIR")
    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 0.0})
    g.addPass(tm, "ToneMapper")
    g.addEdge("VolumetricReSTIR.accumulated_color", "ToneMapper.src")
    g.markOutput("ToneMapper.dst")
    return g


print(f"[streamed] {NAME} frame {FRAME}: extent={extent} scale={scale:.6g} density={density:.6g}")
m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True

os.makedirs(OUT, exist_ok=True)
m.frameCapture.outputDir = str(OUT)
m.frameCapture.baseFilename = "frame"
m.frameCapture.addFrames(m.activeGraph, [ACC])
# Margin: captureToFile writes asynchronously, so quitting on the capture truncates the file.
m.clock.exitFrame = ACC + 60
