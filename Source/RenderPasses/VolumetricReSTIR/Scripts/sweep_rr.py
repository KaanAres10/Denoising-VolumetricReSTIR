# Exhaustive sweep of every Ray Reconstruction configuration, scored against the converged
# reference. Run with a NORMAL python (not inside Mogwai) -- it launches Mogwai once per cell:
#
#     python sweep_rr.py
#     python sweep_rr.py --frames 200 --skip-existing
#
# The search space is the whole one, not a sample of it:
#
#   profile x preset  =  {DLAA, MaxQuality, Balanced, MaxPerf} x {Default, D, E}
#
# and that IS complete for RR: nvsdk_ngx_defs_dlssd.h (310.7.0) documents A/B/C as removed and F..O
# as "do not use, reverts to default behavior", leaving D (default transformer) and E (latest) plus
# Default (let NGX choose). Super Resolution is different -- there J/K are the transformer presets --
# so do not carry a preset letter across from one feature to the other.
#
# Why this needed re-measuring at all: NGX reads the render-preset hint belonging to the quality
# level being created, and the wrapper originally set only the DLAA one. Every upscaling profile
# therefore ignored the preset and silently used NGX's default network.

import argparse
import os
import re
import subprocess
import sys

REPO = r"C:\research\Denoising-VolumetricReSTIR"
BIN = REPO + r"\build\windows-vs2022\bin\Release"
MOGWAI = BIN + r"\Mogwai.exe"
COMPARE = BIN + r"\ImageCompare.exe"
SCRIPT = REPO + r"\Source\RenderPasses\VolumetricReSTIR\Scripts\compare_denoisers_plume.py"
OUT = REPO + r"\shots\sweep_rr"
REFERENCE = REPO + r"\shots\v11\v11_reference.Accum.output.3000.exr"

# The complete NVSDK_NGX_PerfQuality_Value set, in NVIDIA's UI order. SDK name -> UI name:
# MaxQuality = "Quality", MaxPerf = "Performance", UltraQuality was specified but never shipped.
# UltraQuality is omitted deliberately: it is declared in nvsdk_ngx_defs.h but NGX rejects it at
# feature creation with NVSDK_NGX_Result_FAIL_UnsupportedParameter (0xbad00010) -- specified, never
# implemented, consistent with it never shipping commercially. Five usable modes, not six.
PROFILES = ["DLAA", "MaxQuality", "Balanced", "MaxPerf", "UltraPerformance"]
# "Default" is omitted: it measured bit-identical to D at all four profiles of the first sweep, which
# is exactly what nvsdk_ngx_defs_dlssd.h claims ("D = Default model"). D and E are the real choice --
# and both are transformer models, since the convolutional ones are the presets NVIDIA removed.
PRESETS = ["D", "E"]
# Linear ratio -> fraction of the pixels traced (the square of this). DLAA is native.
RATIO = {"DLAA": 1.0, "UltraQuality": 1.0 / 1.3, "MaxQuality": 2.0 / 3.0,
         "Balanced": 0.58, "MaxPerf": 0.5, "UltraPerformance": 1.0 / 3.0}

# The non-RR columns, for context in the same table.
BASELINES = [("none", "raw ReSTIR"), ("oidn", "OIDN GPU"), ("optix", "OptiX temporal")]


def run_mogwai(env_extra, timeout):
    env = dict(os.environ)
    env.update({k: str(v) for k, v in env_extra.items()})
    try:
        # --headless: no window per cell. A sweep otherwise opens and closes one window per run,
        # which is unusable to sit next to. Frame capture and resizeSwapChain both work without it.
        p = subprocess.run([MOGWAI, "--headless", "--script", SCRIPT], env=env, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        return p.stdout
    except subprocess.TimeoutExpired as e:
        return e.output or ""


def metric(image, name):
    """`image` vs the converged reference. Metric names are lowercase, and ImageCompare exits
    non-zero whenever the error exceeds its (unset, so zero) threshold -- so the return code says
    nothing and only the printed number matters."""
    # REFERENCE FIRST. MAPE is asymmetric -- it normalises by the first image -- so the ground truth
    # has to be the divisor or the percentages are relative to the noisy estimate instead. Getting
    # this backwards inflated raw ReSTIR from 10.35 to 16.27 while MSE, being symmetric, was
    # unchanged: agreement on MSE is NOT evidence the arguments are the right way round.
    p = subprocess.run([COMPARE, "-m", name, REFERENCE, image],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    match = re.search(r"([-+0-9.eE]+)\s*$", p.stdout.strip())
    return float(match.group(1)) if match else float("nan")


def find_capture(tag):
    if not os.path.isdir(OUT):
        return None
    hits = [f for f in os.listdir(OUT) if f.startswith(tag + ".") and f.endswith(".exr")]
    return os.path.join(OUT, sorted(hits)[-1]) if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=200)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--skip-existing", action="store_true", help="reuse captures already on disk")
    ap.add_argument("--baselines", action="store_true", help="also re-measure none/oidn/optix")
    # RR carries a temporal history and the camera is jittered, so repeat runs are NOT identical.
    # Without repeats there is no way to tell an 11% gap between two profiles from measurement noise
    # -- and one cell of the first sweep came back 170x off, so the tail is not benign.
    ap.add_argument("--repeat", type=int, default=1, help="render each cell N times; report mean and spread")
    args = ap.parse_args()

    if not os.path.isfile(REFERENCE):
        sys.exit("missing ground truth: %s\nRun the 'V11: reference (3000spp ground truth)' task first."
                 % REFERENCE)
    os.makedirs(OUT, exist_ok=True)

    cells = []
    if args.baselines:
        cells += [(m, None, None, label) for m, label in BASELINES]
    for profile in PROFILES:
        for preset in PRESETS:
            # DLAA is native, so it is the 'rr' mode; every other profile upscales.
            mode = "rr" if profile == "DLAA" else "rr_upscale"
            cells.append((mode, profile, preset, "RR %s / preset %s" % (profile, preset)))

    rows = []
    for i, (mode, profile, preset, label) in enumerate(cells, 1):
        base = "sw_" + mode + (("_" + profile + "_" + preset) if profile else "")
        print("[%2d/%d] %-32s" % (i, len(cells), label), end=" ", flush=True)

        samples = []
        for rep in range(args.repeat):
            tag = base if args.repeat == 1 else "%s_r%d" % (base, rep + 1)
            img = find_capture(tag) if args.skip_existing else None
            if img is None:
                # Let the run exit itself once the capture has flushed; the timeout is a backstop.
                env = {"VR_MODE": mode, "VR_FRAMES": args.frames, "VR_OUT_DIR": OUT, "VR_TAG": tag,
                       "VR_EXIT_AFTER_CAPTURE": "1"}
                if profile:
                    env.update({"VR_PROFILE": profile, "VR_PRESET": preset})
                log = run_mogwai(env, args.timeout)
                img = find_capture(tag)
                if img is None:
                    err = next((l for l in log.splitlines() if "Error" in l or "xception" in l),
                               "no capture written")
                    print("FAILED -- " + err.strip()[:100], end=" ")
                    continue
            samples.append((metric(img, "mse"), metric(img, "mape")))

        if not samples:
            print("")
            continue
        mses = [s[0] for s in samples]
        mse, mape = sum(mses) / len(mses), sum(s[1] for s in samples) / len(samples)
        spread = (max(mses) - min(mses)) / mse if len(mses) > 1 else 0.0
        frac = RATIO.get(profile, 1.0) ** 2 if profile else 1.0
        rows.append((label, frac, mse, mape, spread, len(samples)))
        print("MSE %.4e  MAPE %.2f%s" % (mse, mape, "  spread %.1f%%" % (100 * spread) if spread else ""))

    rows.sort(key=lambda r: r[2])
    print("\n| Configuration | pixels traced | MSE | MAPE |%s" % (" spread | n |" if args.repeat > 1 else ""))
    print("|---|---|---|---|" + ("---|---|" if args.repeat > 1 else ""))
    for label, frac, mse, mape, spread, n in rows:
        extra = " %.1f%% | %d |" % (100 * spread, n) if args.repeat > 1 else ""
        print("| %s | %.0f%% | %.3e | %.2f |%s" % (label, 100 * frac, mse, mape, extra))


if __name__ == "__main__":
    main()
