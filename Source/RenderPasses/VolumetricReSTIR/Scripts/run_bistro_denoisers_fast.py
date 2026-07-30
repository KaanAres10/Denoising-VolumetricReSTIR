# Bistro with every denoiser available, but only the one you are looking at is actually computed.
#
# HOW TO SWITCH (one-time step each session):
#   In Mogwai's "Graphs" panel, tick the "List All Outputs" checkbox. The Output dropdown then lists
#   every branch below; picking one computes it and drops the previous one.
#
#     ToneMapper_BASE.dst        raw ReSTIR, no denoising      <- the only one marked in this script
#     ToneMapper_OIDN_GPU.dst    Intel OIDN, CUDA
#     ToneMapper_OIDN_CPU.dst    Intel OIDN, CPU
#     ToneMapper_OPTIX.dst       NVIDIA OptiX AI denoiser
#     ToneMapper_REFERENCE.dst   AccumulatePass, converges to ground truth
#
# WHY THIS IS THE EFFICIENT ONE. A render graph culls any pass that does not feed a marked output.
# Mogwai refuses to unmark outputs the script marked -- Renderer::markOutput/unmarkOutput both begin
# "if (isInVector(graphData.originalOutputs, name)) return;" -- so anything marked here is pinned and
# can never be culled. run_bistro_denoisers.py marks all five, so all five run every frame. This
# script marks only BASE (the cheapest branch: no denoiser, just a tone map), leaving the rest
# unmarked. Mogwai marks and unmarks those on demand as you change the dropdown, so the denoiser you
# are not viewing costs nothing.
#
# TWO CONSEQUENCES, both intentional:
#   1. Branches see different ReSTIR samples, since only one is live at a time. Good for eyeballing
#      a single denoiser; use run_bistro_denoisers.py when you need a sample-exact A/B comparison.
#   2. REFERENCE only accumulates while it is on screen -- switch away and its convergence stalls.
#
# Opening a debug window forces "List All Outputs" on (Mogwai.cpp:268) and pins that output too, so
# a second view costs you its branch continuously -- which is exactly how you get two side by side.
#
# Run:  Mogwai.exe --script run_bistro_denoisers_fast.py

# The OptiX branch is ON by default. Set VR_OPTIX=0 to drop it if the driver is too old: OptiX
# requires the driver to match the SDK's ABI (8.1 -> 93, 9.0 -> 105, 9.1 -> 118), and SDK 9.1 needs
# driver 610.74 or newer, else optixInit() fails with OPTIX_ERROR_UNSUPPORTED_ABI_VERSION.
#
# That failure cannot be guarded with try/except: OptixDenoiser_::compile() calls optixInit() at
# *graph compile* time, long after createPass() returned, so selecting that output would take down
# the whole graph. Hence the env switch rather than a caught exception.

import os

from falcor import *

DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"
USE_OPTIX = os.environ.get("VR_OPTIX", "1") not in ("0", "", "false", "False")

m.loadScene(DATA_DIR + r"\Bistro_5_1\BistroExterior.fbx")

# Dense smoke plume (fork's original parameters). sigma_s=80 is what gives the plume its density,
# structure and coloured scattering -- thinning it out washes both the detail and the colour away.
m.scene.addGVDBVolume(sigma_a=float3(10, 10, 10), sigma_s=float3(80, 80, 80), g=0.0,
                      dataFile=DATA_DIR + r"\smoke-plume-2", numMips=4)

m.scene.camera.position = float3(-15.149291, 8.352362, -8.399609)
m.scene.camera.target = float3(-14.742913, 8.025879, -7.546224)
m.scene.camera.up = float3(0.004061, 0.999961, 0.007782)

# Shared tone mapping, so the only difference between branches is the denoiser.
TONEMAP = {'autoExposure': False, 'exposureCompensation': 8.0}


def add_branch(g, label, denoiser, src, dst):
    """Wire VolumetricReSTIR -> <denoiser> -> ToneMapper_<label>. Deliberately does NOT mark the
    output -- Mogwai marks it on demand, which is what allows the branch to be culled when unused.
    Returns the output name, or None if the denoiser could not be created."""
    try:
        if denoiser is not None:
            g.addPass(createPass(denoiser), label)
    except Exception as e:
        print("[denoisers] skipping " + label + ": " + str(e))
        return None

    tm_name = "ToneMapper_" + label
    g.addPass(createPass("ToneMapper", TONEMAP), tm_name)

    if denoiser is None:
        g.addEdge("VolumetricReSTIR.accumulated_color", tm_name + ".src")
    else:
        g.addEdge("VolumetricReSTIR.accumulated_color", label + "." + src)
        g.addEdge(label + "." + dst, tm_name + ".src")

    return tm_name + ".dst"


def render_graph():
    g = RenderGraph("Bistro Denoisers (lazy)")

    vr = createPass("VolumetricReSTIR", {'mParams': {
        'mUseSurfaceScene': True,        # shade the Bistro geometry (surface-scene path)
        'mUseEmissiveLights': True,      # the scene's many emissive lights
        'mUseEnvironmentLights': False,  # night scene, no sky contribution
        'mTemporalReuseMThreshold': 10.0,
    }})
    g.addPass(vr, "VolumetricReSTIR")

    base = add_branch(g, "BASE", None, None, None)
    outputs = [base]
    outputs.append(add_branch(g, "OIDN_GPU", "OIDNGPUPass", "src", "dst"))
    outputs.append(add_branch(g, "OIDN_CPU", "OIDNCPUPass", "src", "dst"))
    if USE_OPTIX:
        # The OptiX pass names its channels color/output rather than src/dst.
        outputs.append(add_branch(g, "OPTIX", "OptixDenoiser", "color", "output"))
    else:
        print("[denoisers] OptiX branch omitted (VR_OPTIX=0)")

    # Converged ground truth: accumulate instead of denoise.
    g.addPass(createPass("AccumulatePass", {'enabled': True}), "Accum")
    g.addPass(createPass("ToneMapper", TONEMAP), "ToneMapper_REFERENCE")
    g.addEdge("VolumetricReSTIR.accumulated_color", "Accum.input")
    g.addEdge("Accum.output", "ToneMapper_REFERENCE.src")
    outputs.append("ToneMapper_REFERENCE.dst")

    # Mark ONLY the cheapest branch. Everything else stays unmarked so Mogwai can cull it.
    g.markOutput(base)

    print("[denoisers] tick 'List All Outputs' in the Graphs panel, then pick from:")
    for o in outputs:
        if o:
            print("    " + o + ("   (marked, always computed)" if o == base else ""))
    return g


m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True
