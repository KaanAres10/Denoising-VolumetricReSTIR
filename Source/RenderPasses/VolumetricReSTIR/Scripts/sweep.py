# Scene-parameterised denoiser sweep, scored against a converged reference.
#
#     python sweep.py --scene plume
#     python sweep.py --scene bistro --repeat 3
#
# Supersedes sweep_rr.py, which was plume-only and pointed at the old 3000-sample reference.
# Runs with a NORMAL python (not inside Mogwai); it launches Mogwai once per cell, headless.
#
# Two corrections are baked in versus the earlier sweeps:
#
#   * The references are the CONVERGED ones. The old plume reference (3000 samples) carried ~2.5e-5
#     of its own noise -- about 20% of the best RR result -- which inflated every row. Measured:
#     mse(3000, 30000) = 2.75e-05.
#   * Bistro runs with VR_FREEZE_ANIM=1. Its FBX animates, so an unfrozen accumulation averages
#     thousands of different scene states and never converges: 500-vs-3000 was 4.7e-4 unfrozen and
#     9.7e-7 frozen. Error that GROWS with more samples is drift, not noise.

import argparse
import ctypes
import os
import re
import subprocess
import sys

REPO = r"C:\research\Denoising-VolumetricReSTIR"
BIN = REPO + r"\build\windows-vs2022\bin\Release"
MOGWAI = BIN + r"\Mogwai.exe"
COMPARE = BIN + r"\ImageCompare.exe"
SCRIPT = REPO + r"\Source\RenderPasses\VolumetricReSTIR\Scripts\run.py"
OUT_ROOT = REPO + r"\shots\sweep"

REFERENCES = {
    "plume": REPO + r"\shots\reference\plume_ref30k.Accum.output.30000.exr",
    "bistro": REPO + r"\shots\reference\bfrz3000.Accum.output.3000.exr",
}

# Linear ratio per DLSS profile; the PIXEL count is its square. UltraQuality is absent deliberately:
# NGX rejects it for Ray Reconstruction with FAIL_UnsupportedParameter -- declared, never implemented.
RATIO = {"DLAA": 1.0, "MaxQuality": 2.0 / 3.0, "Balanced": 0.58, "MaxPerf": 0.5,
         "UltraPerformance": 1.0 / 3.0}

def nrd_label():
    """Name the NRD row after the SDK that is actually deployed.

    Both SDKs can be vendored at once and FALCOR_USE_NRD4 selects between them at configure time, so
    a hardcoded label silently mislabels half the runs -- and the two are far enough apart that
    attributing one's numbers to the other would be a real error, not a cosmetic one. The DLL is the
    ground truth: it is what deploycommon.bat copied next to Mogwai.
    """
    dll = os.path.join(BIN, "NRD.dll")
    try:
        import ctypes.wintypes as wt
        size = ctypes.windll.version.GetFileVersionInfoSizeW(dll, None)
        buf = ctypes.create_string_buffer(size)
        ctypes.windll.version.GetFileVersionInfoW(dll, 0, size, buf)
        ptr, n = ctypes.c_void_p(), ctypes.c_uint()
        ctypes.windll.version.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(n))
        ffi = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint * 4)).contents
        major = ffi[2] >> 16  # dwFileVersionMS high word
    except Exception:
        return "NRD RELAX (version unknown)"
    # Qualified deliberately: v3.1 has no SH/SG variants, and NVIDIA's "comparable with DLSS-RR"
    # claim is specifically about SH mode, which only exists from v4.
    return "NRD v3.1 RELAX" if major == 3 else "NRD v%d RELAX" % major


# Non-upscaling denoisers, all at native resolution.
BASELINES = [
    ("none", "raw ReSTIR"),
    ("oidn", "OIDN GPU"),
    ("optix", "OptiX temporal"),
    ("nrd", nrd_label()),
]

# Ray Reconstruction. Only D and E exist (A/B/C removed, F..O documented "do not use"), and
# Default measured bit-identical to D, so it is not swept.
RR_PROFILES = ["DLAA", "MaxQuality", "Balanced", "MaxPerf", "UltraPerformance"]
RR_PRESETS = ["D", "E"]


def run_mogwai(env_extra, timeout):
    env = dict(os.environ)
    env.update({k: str(v) for k, v in env_extra.items()})
    try:
        p = subprocess.run([MOGWAI, "--headless", "--script", SCRIPT], env=env, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        return p.stdout
    except subprocess.TimeoutExpired as e:
        return e.output or ""


def metric(reference, image, name):
    """REFERENCE FIRST. MAPE normalises by the first image, so the ground truth has to be the
    divisor. ImageCompare also exits non-zero whenever error exceeds its (unset) threshold, so the
    return code says nothing -- only the printed number matters."""
    p = subprocess.run([COMPARE, "-m", name, reference, image],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # Require a digit: ImageCompare's failure messages ("... do not match.") end in a '.', which the
    # old pattern happily matched and then failed to parse. A bad comparison must surface as NaN,
    # not as an exception that aborts the remaining cells.
    match = re.search(r"([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*$", p.stdout.strip())
    if not match:
        print("\n    [compare failed] %s: %s" % (name, p.stdout.strip()[:120]))
        return float("nan")
    return float(match.group(1))


# The denoised result channel, per mode. Must be an explicit priority list: run.py also marks the
# guide buffers (DLSSDGuides.*, mediumAlpha) for inspection, so a cell writes several EXRs and
# picking by sort order silently grabbed mediumAlpha -- a single-channel coverage texture that
# scored 8.4e-2 and crashed the comparison on upscaled cells where its size differs.
RESULT_CHANNELS = [
    "DLSSDPass.output",                    # rr
    "ModulateIllumination.output",         # nrd
    "Denoiser.dst",                        # oidn / oidncpu
    "Denoiser.output",                     # optix
    "DLSSPass.output",                     # sr
    "VolumetricReSTIR.accumulated_color",  # none -- the raw estimate IS the result
]


def find_capture(out_dir, tag):
    if not os.path.isdir(out_dir):
        return None
    names = [f for f in os.listdir(out_dir) if f.startswith(tag + ".") and f.endswith(".exr")]
    for channel in RESULT_CHANNELS:
        for f in names:
            if f.startswith(tag + "." + channel + "."):
                return os.path.join(out_dir, f)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="plume", choices=sorted(REFERENCES))
    ap.add_argument("--frames", type=int, default=200)
    ap.add_argument("--timeout", type=int, default=400)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--no-rr", action="store_true", help="baselines only")
    # Quality alone cannot answer a compute-budget question: a denoiser that halves the error for
    # triple the cost is not obviously a win. Adds a second run per cell, so it is opt-in.
    ap.add_argument("--time", action="store_true", help="also measure wall-clock frame time")
    ap.add_argument("--time-frames", type=int, default=120)
    args = ap.parse_args()

    reference = REFERENCES[args.scene]
    if not os.path.isfile(reference):
        sys.exit("missing reference: %s" % reference)
    out_dir = os.path.join(OUT_ROOT, args.scene)
    os.makedirs(out_dir, exist_ok=True)

    cells = [(m, None, None, label) for m, label in BASELINES]
    if not args.no_rr:
        for profile in RR_PROFILES:
            for preset in RR_PRESETS:
                cells.append(("rr", profile, preset, "RR %s / preset %s" % (profile, preset)))

    rows = []
    for i, (mode, profile, preset, label) in enumerate(cells, 1):
        base = "%s_%s%s" % (args.scene, mode, ("_%s_%s" % (profile, preset)) if profile else "")
        print("[%2d/%d] %-34s" % (i, len(cells), label), end=" ", flush=True)

        samples = []
        for rep in range(args.repeat):
            tag = base if args.repeat == 1 else "%s_r%d" % (base, rep + 1)
            img = find_capture(out_dir, tag) if args.skip_existing else None
            if img is None:
                env = {"VR_SCENE": args.scene, "VR_DENOISER": mode, "VR_TONEMAP": "0",
                       "VR_CAPTURE_FRAME": args.frames,
                       "VR_EXIT_AFTER_CAPTURE": "1", "VR_OUT_DIR": out_dir, "VR_TAG": tag,
                       # The scene animation must be frozen or the frame is not the frame the
                       # reference was accumulated from -- these references are frozen at t=0.
                       # NOTE this is also what makes the NRD rows understate NRD: with a temporally
                       # stable input its variance estimator reads "converged" and it stops
                       # filtering. See Source/RenderPasses/NRDPass/README.md. Ranking a temporal
                       # denoiser needs the per-frame reference workflow (VR_HOLD_AT) instead.
                       "VR_FREEZE_ANIM": "1"}
                if profile:
                    env.update({"VR_UPSCALE": "0" if profile == "DLAA" else "1",
                                "VR_PROFILE": profile, "VR_PRESET": preset})
                else:
                    env["VR_UPSCALE"] = "0"
                log = run_mogwai(env, args.timeout)
                img = find_capture(out_dir, tag)
                if img is None:
                    err = next((l for l in log.splitlines() if "Error" in l or "xception" in l),
                               "no capture written")
                    print("FAILED -- " + err.strip()[:100], end=" ")
                    continue
            samples.append((metric(reference, img, "mse"), metric(reference, img, "mape")))

        if not samples:
            print("")
            continue
        mses = [s[0] for s in samples]
        mse = sum(mses) / len(mses)
        mape = sum(s[1] for s in samples) / len(samples)
        spread = (max(mses) - min(mses)) / mse if len(mses) > 1 else 0.0
        frac = RATIO.get(profile, 1.0) ** 2 if profile else 1.0

        ms = float("nan")
        if args.time:
            env = {"VR_SCENE": args.scene, "VR_DENOISER": mode, "VR_FREEZE_ANIM": "1",
                   "VR_TIME_FRAMES": args.time_frames}
            if profile:
                env.update({"VR_UPSCALE": "0" if profile == "DLAA" else "1",
                            "VR_PROFILE": profile, "VR_PRESET": preset})
            else:
                env["VR_UPSCALE"] = "0"
            log = run_mogwai(env, args.timeout)
            match = re.search(r"\[timing\]\s+([0-9.]+)\s+ms/frame", log)
            if match:
                ms = float(match.group(1))

        rows.append((label, frac, mse, mape, spread, len(samples), ms))
        print("MSE %.4e  MAPE %.2f%s%s"
              % (mse, mape,
                 "  spread %.1f%%" % (100 * spread) if spread else "",
                 "  %.1f ms" % ms if args.time and ms == ms else ""))

    rows.sort(key=lambda r: r[2])

    # Denoiser cost is the interesting figure, not total frame time -- the estimator's cost is
    # common to every row. Subtract the undenoised baseline where we have it.
    baseline_ms = next((r[6] for r in rows if r[0] == "raw ReSTIR"), float("nan"))

    hdr = "| Configuration | pixels traced | MSE | MAPE |"
    sep = "|---|---|---|---|"
    if args.repeat > 1:
        hdr += " spread | n |"
        sep += "---|---|"
    if args.time:
        # "net vs raw", not "denoiser cost": an upscaled row traces fewer pixels, so its delta is the
        # denoiser's cost MINUS the sampling saved. Negative means the whole frame got cheaper.
        hdr += " ms/frame | net vs raw |"
        sep += "---|---|"
    print("\n### %s (reference: %s)\n" % (args.scene, os.path.basename(reference)))
    print(hdr)
    print(sep)
    caveats = []
    # Printed with the table, not buried in a docstring: both of these have already been misread
    # once, and a bare number in a markdown table is exactly what gets copied into a report.
    if args.scene == "bistro":
        caveats.append("bistro is a night exterior (+8 EV); MSE is dominated by near-black pixels and "
                       "is nearly blind to visible noise, while a denoiser's bias is not. This column "
                       "ranks least-BIAS, not least-noise -- it cannot rank denoisers.")
    caveats.append("frozen at t=0, so the NRD row understates NRD: its variance estimator is temporal "
                   "and reads a temporally stable input as converged. Use VR_HOLD_AT for a per-frame "
                   "reference. See Source/RenderPasses/NRDPass/README.md.")
    for label, frac, mse, mape, spread, n, ms in rows:
        line = "| %s | %.0f%% | %.3e | %.2f |" % (label, 100 * frac, mse, mape)
        if args.repeat > 1:
            line += " %.1f%% | %d |" % (100 * spread, n)
        if args.time:
            cost = ms - baseline_ms
            line += " %s | %s |" % ("%.1f" % ms if ms == ms else "-",
                                    "%+.1f ms" % cost if cost == cost else "-")
        print(line)
    for c in caveats:
        print("\nCAVEAT: " + c)
    if args.time:
        print("\nFrame times are wall-clock end-to-end (CPU submit + GPU + present), not GPU-only:")
        print("Mogwai exposes no device to Python, so Falcor's profiler is unreachable from a script.")
        print("Treat them as an upper bound. NRD additionally forces a command-list flush per frame.")


if __name__ == "__main__":
    main()
