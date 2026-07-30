# Bistro, rendered to a file instead of to the screen. Same scene, camera and volume parameters as
# run_bistro.py -- the only additions are the frameCapture setup at the bottom.
#
# IMPORTANT: the capture frame is registered with frameCapture.addFrames() and Mogwai's own main
# loop drives the rendering. Do NOT call m.renderFrame() in a loop from this script: that renders
# frames during scene loading, before the app loop starts, so the normal per-frame Scene::update
# never runs. Bistro's ~20k emissive triangles then never finish building their LightCollection and
# the scene renders unlit (near-black, with only the emitters visible as bright dots).
#
# Writes "<OUT_DIR>/bistro.ToneMapper.dst.<frame>.png". Mogwai stays open afterwards; close it when
# the file appears.
#
# Run:  Mogwai.exe --script capture_bistro.py
#       (or VS Code -> Run Task -> "Capture: bistro (to shots/)")

import os

from falcor import *

DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"
OUT_DIR = os.environ.get("VR_OUT_DIR", r"C:\research\Denoising-VolumetricReSTIR\shots")
CAPTURE_AT = int(os.environ.get("VR_CAPTURE_FRAME", "300"))

# Optional denoiser: unset/"none" for the converged reference, or OIDNGPUPass / OIDNCPUPass /
# OptixDenoiser. The OptiX pass uses color/output instead of src/dst.
DENOISER = os.environ.get("VR_DENOISER", "none")

m.loadScene(DATA_DIR + r"\Bistro_5_1\BistroExterior.fbx")

# Dense smoke plume (fork's original parameters). sigma_s=80 is what gives the plume its density,
# structure and coloured scattering -- thinning it out washes both the detail and the colour away.
m.scene.addGVDBVolume(sigma_a=float3(10, 10, 10), sigma_s=float3(80, 80, 80), g=0.0,
                      dataFile=DATA_DIR + r"\smoke-plume-2", numMips=4)

m.scene.camera.position = float3(-15.149291, 8.352362, -8.399609)
m.scene.camera.target = float3(-14.742913, 8.025879, -7.546224)
m.scene.camera.up = float3(0.004061, 0.999961, 0.007782)


def render_graph():
    g = RenderGraph("Bistro Capture")
    vr = createPass("VolumetricReSTIR", {'mParams': {
        'mUseSurfaceScene': True,        # shade the Bistro geometry (surface-scene path)
        'mUseEmissiveLights': True,      # the scene's many emissive lights
        'mUseEnvironmentLights': False,  # night scene, no sky contribution
        'mTemporalReuseMThreshold': 10.0,
    }})
    g.addPass(vr, "VolumetricReSTIR")
    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 8.0})
    g.addPass(tm, "ToneMapper")

    if DENOISER in ("", "none", "None"):
        # Converged ground truth: accumulate many frames, no denoiser.
        acc = createPass("AccumulatePass", {'enabled': True})
        g.addPass(acc, "AccumulatePass")
        g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
        g.addEdge("AccumulatePass.output", "ToneMapper.src")
    else:
        dn = createPass(DENOISER)
        g.addPass(dn, "Denoiser")
        src, dst = ("color", "output") if DENOISER == "OptixDenoiser" else ("src", "dst")
        g.addEdge("VolumetricReSTIR.accumulated_color", "Denoiser." + src)
        g.addEdge("Denoiser." + dst, "ToneMapper.src")

    g.markOutput("ToneMapper.dst")
    return g


m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True

os.makedirs(OUT_DIR, exist_ok=True)
m.frameCapture.outputDir = OUT_DIR
m.frameCapture.baseFilename = "bistro" if DENOISER in ("", "none", "None") else "bistro_" + DENOISER
m.frameCapture.addFrames(m.activeGraph, [CAPTURE_AT])
