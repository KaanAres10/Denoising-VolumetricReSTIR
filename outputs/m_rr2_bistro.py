# RR2 vs previous Ray Reconstruction against a converged ground truth on BISTRO: emissive-lit night
# exterior, surfaces plus the smoke plume. run.py's per-frame-reference workflow (VR_HOLD_AT=200):
# the reference animates to frame 200, holds and accumulates 3000 samples; each denoised run animates to
# frame 200 with real temporal history. Linear HDR throughout.
#
# Scored against the JITTERED reference (VR_REF_JITTER=1) when present: RR returns an anti-aliased
# image, so the quantity it estimates is the pixel-area integral, and against a centre-sampled
# reference every lamp edge on this black background scores as error.
#
# What the metric has to survive, all measured on this scene:
#   * The estimator clamps its output at exactly 1.0 (raw max == 1) while the reference's lamps reach
#     ~6.6, and the frame mean is ~0.003. Directly visible emitters (reference > 1) are excluded -- no
#     denoiser can match them. The pixels right next to them are clamped in the INPUT too (raw is 45%
#     too dark in the 99-99.9th luminance percentile band), and they carry >98% of any absolute MSE,
#     which is why no absolute-error column is reported.
#   * The MEAN relMSE is decided by ~0.1% of pixels (95-99% of the previous RR's surface relMSE sits in
#     its worst 0.1%). Reported, but the per-pixel columns -- median, p90, and the relMSE with the worst
#     0.1% trimmed -- are what say which denoiser is more accurate on a typical pixel.
#
# relMSE per channel = (x' - ref')^2 / (ref'^2 + 1e-2) on images divided by the reference mean;
# rel = |L(x) - L(ref)| / (L(ref) + 0.1 * mean), luminance. Regions from the estimator's mediumAlpha.
#
# Usage: python m_rr2_bistro.py [shots dir] [reference tag]   (default shots/rr2_bistro, best reference)
import glob, os, sys

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2, numpy as np

SHOTS = sys.argv[1] if len(sys.argv) > 1 else r"C:\research\Denoising-VolumetricReSTIR\shots\rr2_bistro"
LUM = np.array([0.0722, 0.7152, 0.2126])  # BGR


def rgb(f):
    return cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float64)


def one(pattern):
    hits = sorted(glob.glob(os.path.join(SHOTS, pattern)))
    return hits[-1] if hits else None


# The 3000-sample reference is visibly NOISY in the smoke lit by the small magenta bulb (two independent
# 3000-sample references differ from each other there by more than either denoiser differs from them),
# so a 12000-sample one is preferred when present; the medium region stays reference-limited either way.
# A second argument names the reference tag explicitly, e.g. rr2b_reference_jit.
REF_TAGS = [sys.argv[2]] if len(sys.argv) > 2 else ["rr2b_reference_jit12k", "rr2b_reference_jit", "rr2b_reference"]
ref_path = next((p for p in (one(t + ".Accum.output.*.exr") for t in REF_TAGS) if p), None)
if ref_path is None:
    raise SystemExit("no reference in " + SHOTS)
ref = rgb(ref_path)
mu = ref.mean()
refn = ref / mu
Lr = refn @ LUM

alpha_path = one("rr2b_prev_E.VolumetricReSTIR.mediumAlpha.*.exr")
alpha = cv2.imread(alpha_path, cv2.IMREAD_UNCHANGED) if alpha_path else None
if alpha is not None:
    # cv2 returns BGR, and the single-channel output is written to R -- index 2, not 0.
    alpha = alpha[..., 2] if alpha.ndim == 3 else alpha
lit = ref.max(axis=2) < 1.0
masks = {"all": lit}
if alpha is not None and alpha.shape == ref.shape[:2]:
    masks["medium"] = lit & (alpha > 0.5)
    masks["surfaces"] = lit & (alpha < 0.05)
print("shots: %s\nreference: %s  mean %.5f" % (SHOTS, os.path.basename(ref_path), mu))
print("pixels scored: " + "  ".join("%s %.1f%%" % (k, 100 * v.mean()) for k, v in masks.items()))

ROWS = [("raw ReSTIR (no denoiser)", "rr2b_none.VolumetricReSTIR.accumulated_color.*.exr"),
        ("DLAA  310.7.0 E", "rr2b_prev_E.DLSSDPass.output.*.exr"),
        ("DLAA  310.9.1 E", "rr2b_cur_E.DLSSDPass.output.*.exr"),
        ("DLAA  310.9.1 F (RR2)", "rr2b_cur_F.DLSSDPass.output.*.exr"),
        ("Balanced 34%  310.7.0 E", "rr2b_bal_prev_E.DLSSDPass.output.*.exr"),
        ("Balanced 34%  310.9.1 F (RR2)", "rr2b_bal_cur_F.DLSSDPass.output.*.exr")]

# Brightness bias in two parts, because one number hides the finding: over the brightest 0.1% of lit
# reference pixels (lamp housings and the surfaces right next to emitters) and over everything else.
for region, m in masks.items():
    hi = m & (Lr >= np.percentile(Lr[m], 99.9))
    lo = m & ~hi
    print("\n[%s]  %-30s %8s %8s %8s %12s %11s %10s %10s" % (region, "", "median", "p90", "p99", "relMSE trim",
                                                          "relMSE mean", "bias 99.9%", "bias top.1%"))
    for label, pat in ROWS:
        f = one(pat)
        if f is None:
            continue
        x = rgb(f) / mu
        if x.shape != refn.shape:
            print("  %-38s size %s != reference %s" % (label, x.shape, refn.shape))
            continue
        per = ((x - refn) ** 2 / (refn ** 2 + 1e-2)).mean(axis=2)[m]
        Lx = x @ LUM
        rel = np.abs(Lx - Lr)[m] / (Lr[m] + 0.1)
        srt = np.sort(per)
        trim = srt[: len(srt) - max(1, len(srt) // 1000)].mean()
        print("  %-38s %8.4f %8.4f %8.4f %12.4f %11.4f %+9.1f%% %+9.1f%%"
              % (label, np.median(rel), np.percentile(rel, 90), np.percentile(rel, 99), trim, per.mean(),
                 100 * (Lx[lo].mean() / Lr[lo].mean() - 1), 100 * (Lx[hi].mean() / Lr[hi].mean() - 1)))
