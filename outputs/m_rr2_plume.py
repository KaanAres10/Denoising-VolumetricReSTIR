# RR2 vs previous Ray Reconstruction against a converged ground truth: static plume, HDR, frame 200.
#
# The reference is RE-RENDERED for this comparison. It came out bit-identical to the July one in
# shots/v11: the plume takes the VBX loader, whose R8 atlas compression skips the mip-0 density that
# brute-force tracking reads, and the scene has no shaded surface for the ray-origin fix to touch.
#
# MSE and MAPE come from ImageCompare, as in sweep_rr.py and the DLSSPass README table -- REFERENCE
# FIRST, since MAPE divides by the first image. NOTE ImageCompare CLAMPS every value to [0, 1] before
# scoring (measured: constant 0 vs 2 scores 1, not 4; on these EXRs its MSE equals numpy's MSE of the
# clamped images to every digit), so those two columns are an LDR-range error, not the HDR error the
# README table describes. Here 2.8% of the reference exceeds 1, mostly the directly visible street
# lamps in the environment map. Kept for continuity with that table, labelled [0,1].
#
# relMSE is the full-range metric and the primary one. Unclamped MSE is useless here -- the lamps reach
# 1e4, so a few thousand pixels decide it. relMSE weights dark and bright regions alike. It is taken on
# images divided by the reference mean (x' = x / mean(ref)), relMSE = mean((x' - ref')^2 / (ref'^2 +
# 1e-2)), the same definition m_rr2_bistro.py needs for a scene whose linear mean is ~0.004.
#
# Each reference present is scored separately: rr2_reference is centre-sampled (the V11 convention),
# rr2_reference_jit is jittered (VR_V11_REF_JITTER=1), i.e. the pixel-area integral an RR row -- a
# jittered, anti-aliased reconstruction -- actually estimates.
#
# Usage: python m_rr2_plume.py [shots dir]   (default shots/rr2 -- the run with the camera's depth range
# left unset; shots/rr2_camfix is the corrected one, see compare_denoisers_plume.py)
import glob, os, re, subprocess, sys
from collections import defaultdict

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2, numpy as np

REPO = r"C:\research\Denoising-VolumetricReSTIR"
SHOTS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "shots", "rr2")
# The denoised colour of each run; VR_V11_INPUTS=1 runs also write guides and depth beside it.
COLOUR = re.compile(r"\.(DLSSDPass\.output|VolumetricReSTIR\.accumulated_color)\.\d+\.exr$")
COMPARE = os.path.join(REPO, r"build\windows-vs2022\bin\Release\ImageCompare.exe")
LABEL = {
    "none": "raw ReSTIR (no denoiser)",
    "dlaa_prev_E": "DLAA   310.7.0 E",
    "dlaa_cur_E": "DLAA   310.9.1 E",
    "dlaa_cur_F": "DLAA   310.9.1 F (RR2)",
    "bal_prev_E": "Balanced 34%  310.7.0 E",
    "bal_cur_E": "Balanced 34%  310.9.1 E",
    "bal_cur_F": "Balanced 34%  310.9.1 F (RR2)",
    # VR_V11_RR_DEPTH=estimator: RR given the estimator's depth instead of the G-buffer's zeros.
    "dlaa_prev_E_zfix": "DLAA   310.7.0 E, est. depth",
    "dlaa_cur_F_zfix": "DLAA   310.9.1 F, est. depth",
    "bal_prev_E_zfix": "Balanced 310.7.0 E, est. depth",
    "bal_cur_F_zfix": "Balanced 310.9.1 F, est. depth",
}
ORDER = ["none", "dlaa_prev_E", "dlaa_cur_E", "dlaa_cur_F", "dlaa_prev_E_zfix", "dlaa_cur_F_zfix",
         "bal_prev_E", "bal_cur_E", "bal_cur_F", "bal_prev_E_zfix", "bal_cur_F_zfix"]


def ic(ref, img, metric):
    p = subprocess.run([COMPARE, "-m", metric, ref, img], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    m = re.search(r"([-+0-9.eE]+)\s*$", p.stdout.strip())
    return float(m.group(1)) if m else float("nan")


def rgb(f):
    return cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float64)


def score(ref_path):
    ref = rgb(ref_path)
    # Brightness bias is read off the pixels below 1: the directly visible lamps reach 1e4, and RR
    # returns them compressed, so a plain mean ratio measures the lamps and nothing else.
    dim = ref.max(axis=2) < 1.0
    print("\nreference: %s  mean %.4f  (%.1f%% of pixels < 1)" % (os.path.basename(ref_path), ref.mean(), 100 * dim.mean()))
    groups = defaultdict(list)
    for f in sorted(glob.glob(os.path.join(SHOTS, "rr2_*.exr"))):
        if not COLOUR.search(f):
            continue
        tag = os.path.basename(f).split(".")[0][4:]
        x = rgb(f)
        xn, rn = x / ref.mean(), ref / ref.mean()
        rel = float(np.mean((xn - rn) ** 2 / (rn ** 2 + 1e-2)))
        groups[re.sub(r"_r\d+$", "", tag)].append(
            (tag, ic(ref_path, f, "mse"), ic(ref_path, f, "mape"), rel, x[dim].mean() / ref[dim].mean()))

    print("%-32s %2s %11s %8s %11s %9s %12s" % ("plume frame 200", "n", "MSE[0,1]", "spread", "relMSE", "MAPE[0,1]", "mean/ref(<1)"))
    for key in ORDER:
        rows = groups.get(key)
        if not rows:
            continue
        mse = [r[1] for r in rows]
        spread = (max(mse) - min(mse)) / np.mean(mse) if len(mse) > 1 else 0.0
        print("%-32s %2d %11.4e %7.1f%% %11.4e %9.2f %12.4f"
              % (LABEL.get(key, key), len(rows), np.mean(mse), 100 * spread, np.mean([r[3] for r in rows]),
                 np.mean([r[2] for r in rows]), np.mean([r[4] for r in rows])))


refs = [p for p in (sorted(glob.glob(os.path.join(SHOTS, "rr2_reference.*.exr"))) +
                    sorted(glob.glob(os.path.join(SHOTS, "rr2_reference_jit.*.exr"))))]
if not refs:
    raise SystemExit("no reference in " + SHOTS)
print("shots:", SHOTS)
for r in refs:
    score(r)
