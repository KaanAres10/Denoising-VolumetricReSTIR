# Bistro with every denoiser wired up at once, so you can flip between them at runtime.
#
# One VolumetricReSTIR pass feeds five branches in parallel, each ending in its own ToneMapper and
# each marked as a graph output:
#
#     BASE       raw ReSTIR, no denoising          (the noise floor to judge against)
#     OIDN_GPU   Intel Open Image Denoise, CUDA
#     OIDN_CPU   Intel Open Image Denoise, CPU     (slow: readback -> denoise -> upload)
#     OPTIX      NVIDIA OptiX AI denoiser
#     REFERENCE  AccumulatePass, no denoiser       (converges to ground truth over ~300 frames)
#
# To switch: use the output dropdown in Mogwai's "Graphs" panel. To compare two at once, open a
# second view from the same panel and point it at a different output.
#
# Every branch runs every frame, so this is deliberately slower than picking one denoiser. That is
# the point -- the images are directly comparable because they share one set of ReSTIR samples.
# Set VR_SKIP_CPU=1 to drop the OIDN CPU branch if the frame rate is too low to work with.
#
# The OptiX branch is ON by default. Set VR_OPTIX=0 to drop it if the driver is too old: OptiX
# requires the driver to match the SDK's ABI (8.1 -> 93, 9.0 -> 105, 9.1 -> 118), and SDK 9.1 needs
# driver 610.74 or newer, else optixInit() fails with OPTIX_ERROR_UNSUPPORTED_ABI_VERSION.
#
# That failure cannot be guarded with try/except: OptixDenoiser_::compile() calls optixInit() at
# *graph compile* time, long after createPass() returned, so it takes down the whole graph rather
# than one branch. Hence the env switch rather than a caught exception.
#
# Run:  Mogwai.exe --script run_bistro_denoisers.py

import os

from falcor import *


def _enabled(name, default="0"):
    return os.environ.get(name, default) not in ("0", "", "false", "False")


DATA_DIR = r"C:\research\Denoising-VolumetricReSTIR\VolumetricReSTIRData"
SKIP_CPU = _enabled("VR_SKIP_CPU")
USE_OPTIX = _enabled("VR_OPTIX", "1")

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
    """Wire VolumetricReSTIR -> <denoiser> -> ToneMapper_<label> and mark the result as an output.
    Returns the output name, or None if the denoiser could not be created."""
    try:
        if denoiser is not None:
            dn = createPass(denoiser)
            g.addPass(dn, label)
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

    out = tm_name + ".dst"
    g.markOutput(out)
    return out


def render_graph():
    g = RenderGraph("Bistro Denoiser Comparison")

    vr = createPass("VolumetricReSTIR", {'mParams': {
        'mUseSurfaceScene': True,        # shade the Bistro geometry (surface-scene path)
        'mUseEmissiveLights': True,      # the scene's many emissive lights
        'mUseEnvironmentLights': False,  # night scene, no sky contribution
        'mTemporalReuseMThreshold': 10.0,
    }})
    g.addPass(vr, "VolumetricReSTIR")

    outputs = []
    outputs.append(add_branch(g, "BASE", None, None, None))
    outputs.append(add_branch(g, "OIDN_GPU", "OIDNGPUPass", "src", "dst"))
    if not SKIP_CPU:
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
    g.markOutput("ToneMapper_REFERENCE.dst")
    outputs.append("ToneMapper_REFERENCE.dst")

    print("[denoisers] available outputs:")
    for o in outputs:
        if o:
            print("    " + o)
    return g


m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True
