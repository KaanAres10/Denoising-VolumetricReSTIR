"""Pixel-correlation metrics for the decorrelation study (docs/superpowers/specs/2026-09-27-restir-mcmc-
decorrelation-design.md), from what Scripts/correlation_pose.py captures.

The headline number is the mean correlation coefficient between a pixel and its neighbours within a
box of radius r, rho(r), averaged over the image -- Sawhney et al. 2024's Eq. 21 covariance, averaged
over a box as in their Table 1, normalised. It is reported raw (Eq. 21 on the raw luminance) and robust
(luminance clamped, and the highest-variance 0.01% of pixels left out), because fireflies spread by
reuse are themselves correlation but dominate a raw covariance. Conclusions use
delta rho(r) = rho_reuse(r) - rho_noreuse(r), since the no-reuse estimator is not guaranteed to be
uncorrelated either (its final shading draws from an R2 sequence).

Every estimate is over K captures that come in R separately seeded chains; confidence intervals come
from a bootstrap over chains, which keeps any dependence inside a chain.

    python m_corr.py <run_dir> --tag T [--out T.corr.json] [--ref ref.exr] [--regions bistro]
                     [--baseline noreuse.corr.json] [--clamp C] [--radii 1,2,4,8,16]
"""
import argparse
import glob
import json
import math
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2
import numpy as np

cv2.setNumThreads(0)

Y_BGR = np.array([0.0722, 0.7152, 0.2126])
Y_RGB = Y_BGR[::-1]
SURFACE_SCENES = ("bistro", "emerald")  # vr_graph scenes with mUseSurfaceScene
BISTRO_REGIONS = {  # forkref/score.py's regions, at 1920x1080
    "plume core": np.s_[250:700, 900:1150], "street": np.s_[800:1080, 0:700], "facade": np.s_[0:300, 0:700],
    "cafe": np.s_[300:800, 1550:1920], "lamp+plume": np.s_[100:1080, 800:1600], "whole": np.s_[:, :]}


# ---------------------------------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------------------------------

def luminance(rgb):
    """Rec. 709 luminance of an (..., 3) array in RGB order."""
    return np.asarray(rgb, dtype=np.float64)[..., :3] @ Y_RGB


def robust_transform(lum, clamp):
    """Clamped, non-finite set to 0. Works on a frame or a stack."""
    x = np.nan_to_num(np.asarray(lum, dtype=np.float64), nan=0.0, posinf=clamp, neginf=0.0)
    return np.minimum(x, clamp)


def pixel_stats(stack):
    """Per-pixel mean and sample standard deviation (ddof=1) over the K frames of a stack."""
    K = len(stack)
    mean = None
    m2 = None
    for k in range(K):  # Welford: stable with 1e5 fireflies next to 1e-3 pixels
        x = np.asarray(stack[k], dtype=np.float64)
        if mean is None:
            mean = np.zeros_like(x)
            m2 = np.zeros_like(x)
        d = x - mean
        mean += d / (k + 1)
        m2 += d * (x - mean)
    std = np.sqrt(np.maximum(m2 / max(K - 1, 1), 0.0))
    return mean, std


def trim_mask(stack=None, fraction=1e-4, std=None):
    """True everywhere except the `fraction` of pixels with the highest variance."""
    if std is None:
        std = pixel_stats(stack)[1]
    n = int(round(fraction * std.size))
    mask = np.ones(std.shape, bool)
    if n > 0:
        worst = np.argpartition(std.ravel(), -n)[-n:]
        mask.ravel()[worst] = False
    return mask


def _integral(x):
    I = np.zeros((x.shape[0] + 1, x.shape[1] + 1))
    I[1:, 1:] = x.cumsum(0).cumsum(1)
    return I


def _box_sum(I, r, shape):
    """Sum over the (2r+1)^2 box around each pixel, clipped to the image (zero outside)."""
    H, W = shape
    y = np.arange(H)
    x = np.arange(W)
    y0, y1 = np.clip(y - r, 0, H), np.clip(y + r + 1, 0, H)
    x0, x1 = np.clip(x - r, 0, W), np.clip(x + r + 1, 0, W)
    return (I[np.ix_(y1, x1)] - I[np.ix_(y0, x1)] - I[np.ix_(y1, x0)] + I[np.ix_(y0, x0)])


def box_rho(stack, radii, mask=None, normalize=True, stats=None):
    """Mean over pixels i of the mean over j in the box of radius r around i (j != i) of
    Corr(i, j) (normalize=True) or Cov(i, j) (normalize=False), both over the K frames with the sample
    mean removed, as in Sawhney et al.'s Eq. 21.

    Pixels with zero variance, or outside `mask`, take no part as centre or neighbour.
    Returns {r: {"value": float, "terms": per-frame terms t_k}}, value = sum_k t_k / (K - 1).
    """
    K = len(stack)
    mean, std = stats if stats is not None else pixel_stats(stack)
    valid = std > 0
    if mask is not None:
        valid &= mask
    m = valid.astype(np.float64)
    Im = _integral(m)
    counts = {}
    for r in radii:
        N = _box_sum(Im, r, m.shape) - m
        centre = valid & (N > 0)
        counts[r] = (N, centre, max(int(centre.sum()), 1))
    inv = np.where(valid, 1.0 / np.where(valid, std, 1.0), 0.0) if normalize else m
    terms = {r: np.zeros(K) for r in radii}
    for k in range(K):
        z = (np.asarray(stack[k], dtype=np.float64) - mean) * inv
        Iz = _integral(z)
        for r in radii:
            N, centre, n = counts[r]
            S = _box_sum(Iz, r, z.shape) - z
            terms[r][k] = np.sum(np.where(centre, z * S / np.where(centre, N, 1.0), 0.0)) / n
    return {r: {"value": float(terms[r].sum() / max(K - 1, 1)), "terms": terms[r]} for r in radii}


def autocorr2d(stack, half=32, mask=None, stats=None):
    """Mean correlation coefficient between pixels offset by (dy, dx), |dy|, |dx| <= half, as a
    (2 half + 1)^2 array indexed [dy + half, dx + half]. Zero-padded FFTs, so lags do not wrap."""
    K = len(stack)
    mean, std = stats if stats is not None else pixel_stats(stack)
    valid = std > 0
    if mask is not None:
        valid &= mask
    H, W = valid.shape
    shape = (H + half, W + half)
    inv = np.where(valid, 1.0 / np.where(valid, std, 1.0), 0.0)
    acc = np.zeros(shape)
    for k in range(K):
        z = (np.asarray(stack[k], dtype=np.float64) - mean) * inv
        F = np.fft.rfft2(z, s=shape)
        acc += np.fft.irfft2(F * np.conj(F), s=shape)
    Fm = np.fft.rfft2(valid.astype(np.float64), s=shape)
    pairs = np.fft.irfft2(Fm * np.conj(Fm), s=shape)
    lags = np.arange(-half, half + 1)
    sub = np.ix_(lags % shape[0], lags % shape[1])
    ac = acc[sub] / max(K - 1, 1)
    n = pairs[sub]
    return np.where(n > 0.5, ac / np.where(n > 0.5, n, 1.0), 0.0)


def radial_profile(ac):
    """Mean of an autocorrelation map over rings of integer radius d = round(|offset|)."""
    h = ac.shape[0] // 2
    dy, dx = np.mgrid[-h:h + 1, -h:h + 1]
    d = np.rint(np.hypot(dy, dx)).astype(int)
    return np.array([ac[d == i].mean() for i in range(h + 1)])


def correlation_length(profile, threshold=0.1):
    """First ring radius whose mean correlation falls below `threshold` (len(profile) if none)."""
    below = np.nonzero(np.asarray(profile) < threshold)[0]
    return int(below[0]) if len(below) else len(profile)


def temporal_rho(series, max_lag):
    """Autocorrelation over time of (T, P) pixel series, each standardised over time, averaged over
    pixels: rho[tau] for tau = 0..max_lag."""
    x = np.asarray(series, dtype=np.float64)
    mu = x.mean(axis=0)
    sd = x.std(axis=0)
    keep = sd > 0
    z = (x[:, keep] - mu[keep]) / sd[keep]
    T = z.shape[0]
    return np.array([np.mean(np.sum(z[:T - t] * z[t:], axis=0) / (T - t)) for t in range(max_lag + 1)])


def decode_identity(rgb):
    """correlation_pose's sampleIdentity capture (RGB order) -> (sample id, light id, at_surface):
    sample -1 and light -9999 where the pixel holds no sample (.z = lightID + 4 >= 1 for every sample);
    at_surface is bit 8 of .y, set where the sample's depth is kRayTMax (a surface or the background)."""
    rgb = np.asarray(rgb, dtype=np.float64)
    valid = rgb[..., 2] > 0
    y = rgb[..., 1].astype(np.int64)
    sample = np.where(valid, rgb[..., 0].astype(np.int64) | ((y & 255) << 24), -1)
    light = np.where(valid, rgb[..., 2].astype(np.int64) - 4, -9999)
    return sample, light, valid & (y >= 256)


def _primary_only(light, at_surface, surface_scene):
    """Samples that are only the pixel's own camera ray: the background, or an emitter seen directly.
    Surface scenes tag them kSelfEmissionLightID (-3); volume-only scenes leave lightID 0."""
    return at_surface & (light == (-3 if surface_scene else 0))


def duplicate_ids(sample, light, at_surface, surface_scene):
    """Sample ids for the exact-sample duplicate count, with primary-ray-only samples dropped (-1): they
    all hash alike but name no shared path."""
    return np.where(_primary_only(light, at_surface, surface_scene), -1, sample)


def light_ids(light, at_surface, surface_scene):
    """Light ids for the light-sharing count: emissive triangles only (id >= 0); the env map (-1) is one
    light for every pixel, and primary-ray-only samples carry none."""
    keep = (light >= 0) & ~_primary_only(light, at_surface, surface_scene)
    return np.where(keep, light, -1)


def duplicate_map(ids, tile=20):
    """Per tile x tile block: pixels holding a sample some other pixel of the block also holds, i.e.
    count(valid) - count(distinct). Ids < 0 are pixels with no sample."""
    H, W = ids.shape[0] // tile, ids.shape[1] // tile
    out = np.zeros((H, W), dtype=np.int64)
    for by in range(H):
        for bx in range(W):
            block = ids[by * tile:(by + 1) * tile, bx * tile:(bx + 1) * tile]
            v = block[block >= 0]
            out[by, bx] = v.size - np.unique(v).size
    return out


def bootstrap_chains(terms, chain_of_frame, n=1000, seed=0):
    """Resample whole chains with replacement; each draw is (K / (K - 1)) * mean of the drawn frames'
    terms, the estimator box_rho uses. Returns (2.5th, 97.5th percentile, draws)."""
    terms = np.asarray(terms, dtype=np.float64)
    chain_of_frame = np.asarray(chain_of_frame)
    K = len(terms)
    chains = np.unique(chain_of_frame)
    sums = np.array([terms[chain_of_frame == c].sum() for c in chains])
    cnts = np.array([(chain_of_frame == c).sum() for c in chains])
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(chains), size=(n, len(chains)))
    draws = (K / max(K - 1, 1)) * sums[pick].sum(axis=1) / cnts[pick].sum(axis=1)
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5)), draws


def reference_errors(stack, ref, regions, trim=1e-4, sigmas=(2, 8, 32)):
    """Against a converged reference: per-region relative bias of the mean image, relMSE per frame (worst
    `trim` of pixels left out, then averaged over frames), and the RMS of the error blurred at each sigma
    over the reference's mean (blotches are low-frequency error, so they survive the blur)."""
    ref = np.asarray(ref, dtype=np.float64)
    K = len(stack)
    total = np.zeros_like(ref)
    relmse = []
    blur = {s: [] for s in sigmas}
    level = max(float(ref.mean()), 1e-12)
    for k in range(K):
        x = np.asarray(stack[k], dtype=np.float64)
        total += x
        e = (x - ref) ** 2 / (ref ** 2 + 1e-4)
        n = int(round(trim * e.size))
        if n > 0:
            e = np.sort(e.ravel())[:-n]
        relmse.append(float(e.mean()))
        for s in sigmas:
            b = cv2.GaussianBlur(x - ref, (0, 0), sigmaX=s)
            blur[s].append(float(np.sqrt(np.mean(b ** 2))) / level)
    mean_img = total / K
    out = {"relmse": float(np.mean(relmse)), "blur_rms": {str(s): float(np.mean(v)) for s, v in blur.items()},
           "regions": {}}
    for name, sl in regions.items():
        r = float(ref[sl].mean())
        out["regions"][name] = {"bias": (float(mean_img[sl].mean()) - r) / max(r, 1e-12), "ref_mean": r}
    return out


# ---------------------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------------------

def read_exr(path):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(path)
    return img


def load_luminance(paths):
    """(K, H, W) float32 luminance of the captures; non-finite values set to 0 and counted."""
    first = read_exr(paths[0])
    out = np.empty((len(paths),) + first.shape[:2], np.float32)
    bad = 0
    for k, p in enumerate(paths):
        img = first if k == 0 else read_exr(p)
        x = img[..., :3].astype(np.float64)
        finite = np.isfinite(x).all(axis=-1)
        bad += int((~finite).sum())
        out[k] = np.where(finite, x @ Y_BGR, 0.0)
    return out, bad


def _rho_block(stack, radii, mask, n_boot, chain_of_frame, stats):
    rho = box_rho(stack, radii, mask=mask, stats=stats)
    cov = box_rho(stack, radii, mask=mask, normalize=False, stats=stats)
    out = {"rho": {}, "cov": {}, "ci": {}, "draws": {}}
    for r in radii:
        lo, hi, draws = bootstrap_chains(rho[r]["terms"], chain_of_frame, n=n_boot, seed=r)
        out["rho"][str(r)] = rho[r]["value"]
        out["cov"][str(r)] = cov[r]["value"]
        out["ci"][str(r)] = [lo, hi]
        out["draws"][str(r)] = draws.round(6).tolist()
    return out, rho


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out")
    ap.add_argument("--radii", default="1,2,4,8,16")
    ap.add_argument("--clamp", type=float, default=None,
                    help="robust clamp; default: the 99.9th percentile of the first 10 captures")
    ap.add_argument("--regions", choices=("none", "bistro"), default="none")
    ap.add_argument("--ref", help="converged reference EXR (correlation_pose VR_MODE=reference)")
    ap.add_argument("--baseline", help="the no-reuse run's .corr.json, for delta rho")
    ap.add_argument("--bootstrap", type=int, default=1000)
    ap.add_argument("--half", type=int, default=32, help="autocorrelation half-width in pixels")
    a = ap.parse_args(argv)
    radii = tuple(int(r) for r in a.radii.split(","))
    with open(os.path.join(a.run_dir, a.tag + ".schedule.json")) as fh:
        sched = json.load(fh)
    # The captured output: the estimator's by default, a denoiser's when correlation_pose ran with one.
    channel = sched.get("channel", "VolumetricReSTIR.accumulated_color")
    color = lambda f: os.path.join(a.run_dir, "%s.%s.%d.exr" % (a.tag, channel, f))
    frames, chain_of_frame, index_in_chain = [], [], []
    for c, chain in enumerate(sched["chains"]):
        for k, f in enumerate(chain["frames"]):
            frames.append(f)
            chain_of_frame.append(c)
            index_in_chain.append(k)
    chain_of_frame = np.array(chain_of_frame)
    index_in_chain = np.array(index_in_chain)
    stack, bad = load_luminance([color(f) for f in frames])
    K = len(frames)
    res = {"run_dir": a.run_dir, "tag": a.tag, "scene": sched.get("scene"), "channel": channel, "K": K,
           "chains": len(sched["chains"]), "per_chain": len(sched["chains"][0]["frames"]),
           "warm": sched.get("warm"), "spacing": sched.get("spacing"), "env": sched.get("env", {}),
           "nonfinite": bad, "radii": list(radii), "mean_level": float(stack.mean())}

    # Raw: Eq. 21 on the raw luminance.
    stats = pixel_stats(stack)
    res["raw"], raw_rho = _rho_block(stack, radii, None, a.bootstrap, chain_of_frame, stats)
    res["raw"]["valid_pixels"] = int((stats[1] > 0).sum())

    # Robust: clamped, highest-variance 0.01% of pixels left out.
    clamp = a.clamp if a.clamp is not None else float(np.percentile(stack[:10], 99.9))
    robust = np.minimum(stack, np.float32(clamp))
    rstats = pixel_stats(robust)
    rmask = trim_mask(std=rstats[1])
    res["robust"], robust_rho = _rho_block(robust, radii, rmask, a.bootstrap, chain_of_frame, rstats)
    res["robust"]["clamp"] = clamp

    # Stationarity: the first vs second half of every chain's captures.
    half = index_in_chain < (index_in_chain.max() + 1) / 2.0
    r8 = 8 if 8 in radii else radii[-1]
    t = robust_rho[r8]["terms"]
    res["stationarity"] = {"radius": r8,
                           "mean_first": float(stack[half].mean()), "mean_second": float(stack[~half].mean()),
                           "rho_first": float(K / (K - 1) * t[half].mean()),
                           "rho_second": float(K / (K - 1) * t[~half].mean())}

    # Spatial structure of the correlation (robust).
    ac = autocorr2d(robust, half=a.half, mask=rmask, stats=rstats)
    prof = radial_profile(ac)
    np.save(os.path.join(a.run_dir, a.tag + ".autocorr.npy"), ac)
    h = a.half
    # The strongest offsets, from one half-plane (the map is symmetric: ac(dy, dx) = ac(-dy, -dx)). A
    # neighbour pattern shared by every pixel shows up here as isolated peaks away from the origin.
    peaks = []
    for idx in np.argsort(ac.ravel())[::-1]:
        dy, dx = (int(v) - h for v in divmod(int(idx), ac.shape[1]))
        if dy > 0 or (dy == 0 and dx > 0):
            peaks.append([dy, dx, float(ac.ravel()[idx])])
            if len(peaks) >= 8:
                break
    rings = {}
    dyy, dxx = np.mgrid[-h:h + 1, -h:h + 1]
    dist = np.rint(np.hypot(dyy, dxx)).astype(int)
    for d in (d for d in (1, 2, 4, 8) if d <= h):
        ring = ac[dist == d]
        rings[str(d)] = {"mean": float(ring.mean()), "max": float(ring.max()), "min": float(ring.min())}
    res["autocorr"] = {"radial": prof.round(5).tolist(), "length_0.1": correlation_length(prof, 0.1),
                       "length_0.05": correlation_length(prof, 0.05), "rings": rings, "top_offsets": peaks}

    # Regions (robust and raw rho at r8).
    if a.regions == "bistro" and stack.shape[1:] == (1080, 1920):
        res["regions"] = {}
        for name, sl in BISTRO_REGIONS.items():
            m = np.zeros(stack.shape[1:], bool)
            m[sl] = True
            rr = box_rho(robust, (r8,), mask=m & rmask, stats=rstats)[r8]["value"]
            rw = box_rho(stack, (r8,), mask=m, stats=stats)[r8]["value"]
            res["regions"][name] = {"rho_robust": rr, "rho_raw": rw, "mean": float(stack[:, m].mean())}

    # Temporal autocorrelation from the burst, on up to 50k valid pixels.
    if sched.get("burst"):
        bf = sched["burst"]["frames"]
        bstack, _ = load_luminance([color(f) for f in bf])
        bstack = np.minimum(bstack, np.float32(clamp))
        valid = np.flatnonzero((bstack.std(axis=0) > 0).ravel())
        rng = np.random.default_rng(0)
        pix = rng.choice(valid, size=min(50000, valid.size), replace=False) if valid.size else valid
        series = bstack.reshape(len(bf), -1)[:, pix]
        lag = min(64, len(bf) - 2)
        tr = temporal_rho(series, lag)
        res["temporal"] = {"rho": tr.round(5).tolist(), "lag_below_0.05": correlation_length(tr, 0.05)}

    # Duplicate samples, from whatever sampleIdentity captures exist (a VR_IDS run).
    ids = sorted(glob.glob(os.path.join(a.run_dir, "%s.VolumetricReSTIR.sampleIdentity.*.exr" % a.tag)))
    if ids:
        surface_scene = sched.get("scene") in SURFACE_SCENES
        dmaps, lmaps = [], []
        for p in ids:
            img = read_exr(p)[..., :3][..., ::-1]
            sample, light, at_surface = decode_identity(img)
            dmaps.append(duplicate_map(duplicate_ids(sample, light, at_surface, surface_scene)))
            lmaps.append(duplicate_map(light_ids(light, at_surface, surface_scene)))
        dmean, lmean = np.mean(dmaps, axis=0), np.mean(lmaps, axis=0)
        np.save(os.path.join(a.run_dir, a.tag + ".dup_sample.npy"), dmean)
        np.save(os.path.join(a.run_dir, a.tag + ".dup_light.npy"), lmean)
        res["duplicates"] = {"frames": len(ids), "tile": 20,
                             "sample_mean": float(dmean.mean()), "sample_max": float(dmean.max()),
                             "light_mean": float(lmean.mean()), "light_max": float(lmean.max())}

    # Against a reference.
    if a.ref:
        ref = read_exr(a.ref)[..., :3].astype(np.float64) @ Y_BGR
        regions = BISTRO_REGIONS if (a.regions == "bistro" and ref.shape == (1080, 1920)) else {"whole": np.s_[:, :]}
        res["reference"] = reference_errors(stack, ref, regions)
        res["reference"]["path"] = a.ref

    # Against the no-reuse baseline.
    if a.baseline:
        with open(a.baseline) as fh:
            base = json.load(fh)
        res["delta"] = {}
        for kind in ("raw", "robust"):
            res["delta"][kind] = {}
            for r in radii:
                key = str(r)
                if key not in base.get(kind, {}).get("rho", {}):
                    continue
                d = np.array(res[kind]["draws"][key]) - np.array(base[kind]["draws"][key])
                res["delta"][kind][key] = {"value": res[kind]["rho"][key] - base[kind]["rho"][key],
                                           "ci": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]}
        res["baseline"] = a.baseline

    out = a.out or os.path.join(a.run_dir, a.tag + ".corr.json")
    with open(out, "w") as fh:
        json.dump(res, fh, indent=1)
    rr, rb = res["raw"]["rho"], res["robust"]["rho"]
    line = "%s K=%d  rho raw %s  robust %s" % (a.tag, K, " ".join("r%s=%.4f" % (k, v) for k, v in rr.items()),
                                              " ".join("r%s=%.4f" % (k, v) for k, v in rb.items()))
    if "delta" in res:
        d = res["delta"]["robust"].get(str(r8))
        if d:
            line += "  delta_robust(r%d)=%.4f [%.4f, %.4f]" % (r8, d["value"], d["ci"][0], d["ci"][1])
    print(line)
    return res


if __name__ == "__main__":
    main()
