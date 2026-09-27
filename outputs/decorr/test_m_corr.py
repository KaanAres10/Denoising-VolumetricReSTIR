"""m_corr.py's statistics on synthetic data with known answers.

    python -m unittest outputs/decorr/test_m_corr.py -v      (or: cd outputs/decorr && python -m unittest test_m_corr)
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_corr as mc

RNG = np.random.default_rng(1234)


def box_blur_wrap(x, a):
    """Circular (2a+1)^2 box mean over the last two axes, so the correlation is stationary."""
    out = np.zeros_like(x)
    for dy in range(-a, a + 1):
        for dx in range(-a, a + 1):
            out += np.roll(np.roll(x, dy, axis=-2), dx, axis=-1)
    return out / (2 * a + 1) ** 2


def analytic_box_rho(a, r):
    """Mean correlation over the (2r+1)^2 box minus the centre, for a (2a+1)^2 box-blurred white noise."""
    w = 2 * a + 1
    vals = [max(0, w - abs(dx)) * max(0, w - abs(dy)) / w ** 2
            for dy in range(-r, r + 1) for dx in range(-r, r + 1) if (dx, dy) != (0, 0)]
    return float(np.mean(vals))


class TestBoxRho(unittest.TestCase):
    def test_box_sum_matches_a_direct_window_sum(self):
        # The box is clipped to the image, including radii wider than the image.
        x = RNG.standard_normal((13, 21))
        I = mc._integral(x)
        for r in (0, 1, 3, 7, 30):
            direct = np.array([[x[max(0, i - r):i + r + 1, max(0, j - r):j + r + 1].sum() for j in range(21)]
                               for i in range(13)])
            np.testing.assert_allclose(mc._box_sum(I, r, x.shape), direct, atol=1e-10, err_msg=str(r))

    def test_frames_scored_in_parallel_match_one_at_a_time(self):
        stack = box_blur_wrap(RNG.standard_normal((24, 40, 56)), 1)
        mask = RNG.random((40, 56)) > 0.2
        for normalize in (True, False):
            one = mc.box_rho(stack, (1, 4, 60), mask=mask, normalize=normalize, workers=1)
            many = mc.box_rho(stack, (1, 4, 60), mask=mask, normalize=normalize, workers=6)
            for r in (1, 4, 60):
                np.testing.assert_array_equal(one[r]["terms"], many[r]["terms"])

    def test_white_noise_has_no_correlation(self):
        stack = RNG.standard_normal((400, 64, 64))
        res = mc.box_rho(stack, radii=(1, 4, 8))
        for r in (1, 4, 8):
            self.assertLess(abs(res[r]["value"]), 0.02, (r, res[r]["value"]))

    def test_box_blurred_noise_matches_analytic(self):
        stack = box_blur_wrap(RNG.standard_normal((400, 128, 128)), 2)
        res = mc.box_rho(stack, radii=(1, 2, 4, 8))
        for r in (1, 2, 4, 8):
            self.assertAlmostEqual(res[r]["value"], analytic_box_rho(2, r), delta=0.03, msg=r)

    def test_covariance_scales_with_variance(self):
        base = box_blur_wrap(RNG.standard_normal((200, 64, 64)), 1)
        c1 = mc.box_rho(base, radii=(2,), normalize=False)[2]["value"]
        c3 = mc.box_rho(3.0 * base, radii=(2,), normalize=False)[2]["value"]
        self.assertAlmostEqual(c3 / c1, 9.0, places=6)

    def test_constant_pixels_are_excluded(self):
        # Review Focus 2: zero-variance pixels (a black background) must not poison the normalisation.
        noisy = box_blur_wrap(RNG.standard_normal((300, 64, 64)), 1)
        stack = noisy.copy()
        stack[:, :, 32:] = 0.0
        full = mc.box_rho(stack, radii=(2,))[2]["value"]
        half = mc.box_rho(noisy[:, :, :32], radii=(2,))[2]["value"]
        self.assertTrue(np.isfinite(full))
        self.assertAlmostEqual(full, half, delta=0.02)

    def test_per_frame_terms_sum_to_the_value(self):
        stack = RNG.standard_normal((50, 32, 32))
        res = mc.box_rho(stack, radii=(3,))[3]
        K = stack.shape[0]
        self.assertAlmostEqual(res["value"], res["terms"].sum() / (K - 1), places=12)
        self.assertEqual(len(res["terms"]), K)


class TestRobust(unittest.TestCase):
    def test_robust_is_finite_with_fireflies(self):
        # Review Focus 4: lamp-edge fireflies (~1e5) in 0.01% of pixel-frames.
        stack = np.abs(RNG.standard_normal((200, 64, 64)))
        idx = RNG.choice(stack.size, size=max(1, stack.size // 10000), replace=False)
        stack.flat[idx] = 1e5
        raw = mc.box_rho(stack, radii=(2,))[2]["value"]
        robust = mc.box_rho(mc.robust_transform(stack, clamp=3.0), radii=(2,),
                            mask=mc.trim_mask(mc.robust_transform(stack, clamp=3.0)))[2]["value"]
        self.assertTrue(np.isfinite(raw) and np.isfinite(robust))
        self.assertLess(abs(robust), 0.05)

    def test_trim_mask_drops_the_highest_variance_pixels(self):
        stack = RNG.standard_normal((100, 100, 100))
        stack[:, 7, 9] *= 1000.0
        mask = mc.trim_mask(stack, fraction=1e-4)
        self.assertFalse(mask[7, 9])
        self.assertEqual(int((~mask).sum()), 1)


class TestAutocorr(unittest.TestCase):
    def test_autocorr_of_blurred_noise(self):
        stack = box_blur_wrap(RNG.standard_normal((200, 96, 96)), 2)
        ac = mc.autocorr2d(stack, half=6)
        c = 6
        self.assertAlmostEqual(ac[c, c], 1.0, delta=0.02)
        self.assertAlmostEqual(ac[c, c + 1], 0.8, delta=0.03)      # (5-1)*5/25
        self.assertAlmostEqual(ac[c + 2, c + 2], 9 / 25, delta=0.03)
        self.assertAlmostEqual(ac[c, c + 6], 0.0, delta=0.03)

    def test_radial_profile_and_length(self):
        stack = box_blur_wrap(RNG.standard_normal((200, 96, 96)), 2)
        prof = mc.radial_profile(mc.autocorr2d(stack, half=8))
        self.assertAlmostEqual(prof[0], 1.0, delta=0.02)
        self.assertTrue(np.all(np.diff(prof[:5]) < 0.02))
        self.assertTrue(2 <= mc.correlation_length(prof, threshold=0.1) <= 6)


class TestTemporal(unittest.TestCase):
    def test_temporal_rho_of_ar1(self):
        T, P, phi = 400, 2000, 0.8
        x = np.zeros((T, P))
        x[0] = RNG.standard_normal(P)
        for t in range(1, T):
            x[t] = phi * x[t - 1] + np.sqrt(1 - phi ** 2) * RNG.standard_normal(P)
        rho = mc.temporal_rho(x, max_lag=3)
        self.assertAlmostEqual(rho[0], 1.0, delta=0.01)
        self.assertAlmostEqual(rho[1], 0.8, delta=0.05)
        self.assertAlmostEqual(rho[2], 0.64, delta=0.05)


class TestDuplicates(unittest.TestCase):
    def test_duplicate_map_counts(self):
        ids = np.arange(40 * 40, dtype=np.int64).reshape(40, 40)
        ids[:20, 20:].flat[:50] = 777777  # 50 pixels of the top-right tile share one sample
        dup = mc.duplicate_map(ids, tile=20)
        self.assertEqual(dup.shape, (2, 2))
        self.assertEqual(dup[0, 1], 49)
        self.assertEqual(dup[0, 0] + dup[1, 0] + dup[1, 1], 0)

    def test_duplicate_map_matches_a_per_tile_count(self):
        # Few distinct ids, so tiles repeat; negatives are pixels with no sample; a partial last tile is dropped.
        ids = RNG.integers(-3, 40, size=(47, 65))
        dup = mc.duplicate_map(ids, tile=10)
        self.assertEqual(dup.shape, (4, 6))
        for by in range(4):
            for bx in range(6):
                v = ids[by * 10:(by + 1) * 10, bx * 10:(bx + 1) * 10]
                v = v[v >= 0]
                self.assertEqual(dup[by, bx], v.size - np.unique(v).size, (by, bx))

    def test_invalid_pixels_are_not_duplicates(self):
        ids = np.full((20, 20), -1, dtype=np.int64)
        self.assertEqual(mc.duplicate_map(ids, tile=20)[0, 0], 0)

    def test_identity_decoding(self):
        rgb = np.zeros((1, 4, 3))
        rgb[0, 0] = (0x123456, 0xAB, 3)      # a medium sample: hash 0xAB123456, lightID -1
        rgb[0, 1] = (0, 0, 0)                # no sample
        rgb[0, 2] = (5, 0, 1)                # lightID -3 (self-emission in the medium)
        rgb[0, 3] = (7, 256 + 5, 4)          # depth = kRayTMax (bit 8 of .y), lightID 0
        sample, light, at_surface = mc.decode_identity(rgb)
        self.assertEqual(sample[0, 0], 0xAB123456)
        self.assertEqual(sample[0, 1], -1)
        self.assertEqual(sample[0, 3], (5 << 24) | 7)
        self.assertEqual(light.tolist(), [[-1, -9999, -3, 0]])
        self.assertEqual(at_surface.tolist(), [[False, False, False, True]])

    def test_primary_ray_only_samples_are_not_duplicates(self):
        # Background pixels (and directly seen emitters) all carry one token, but it names no shared path:
        # each pixel's own camera ray. Volume-only scenes tag the background lightID 0, surface scenes -3.
        sample = np.array([[11, 11, 22, 22]])
        light = np.array([[0, 0, -3, -3]])
        at_surface = np.array([[True, True, True, True]])
        self.assertEqual(mc.duplicate_ids(sample, light, at_surface, surface_scene=False).tolist(), [[-1, -1, 22, 22]])
        self.assertEqual(mc.duplicate_ids(sample, light, at_surface, surface_scene=True).tolist(), [[11, 11, -1, -1]])
        in_medium = np.zeros_like(at_surface)
        self.assertEqual(mc.duplicate_ids(sample, light, in_medium, surface_scene=False).tolist(), [[11, 11, 22, 22]])

    def test_light_sharing_counts_emissive_triangles_only(self):
        light = np.array([[-1, -1, 5, 5, 0, -3]])
        at_surface = np.array([[False, False, False, True, True, False]])
        # env (-1) is one "light" for every pixel; volume-only background is lightID 0 at the surface.
        self.assertEqual(mc.light_ids(light, at_surface, surface_scene=False).tolist(), [[-1, -1, 5, 5, -1, -1]])
        self.assertEqual(mc.light_ids(light, at_surface, surface_scene=True).tolist(), [[-1, -1, 5, 5, 0, -1]])


class TestBootstrap(unittest.TestCase):
    def test_bootstrap_covers_truth(self):
        stack = RNG.standard_normal((100, 48, 48))
        res = mc.box_rho(stack, radii=(4,))[4]
        chains = np.repeat(np.arange(20), 5)
        lo, hi, draws = mc.bootstrap_chains(res["terms"], chains, n=1000, seed=0)
        self.assertLess(lo, 0.0)
        self.assertGreater(hi, 0.0)
        self.assertEqual(len(draws), 1000)

    def test_bootstrap_centre_matches_value(self):
        stack = box_blur_wrap(RNG.standard_normal((100, 48, 48)), 1)
        res = mc.box_rho(stack, radii=(2,))[2]
        lo, hi, draws = mc.bootstrap_chains(res["terms"], np.repeat(np.arange(20), 5), n=2000, seed=1)
        self.assertLess(lo, res["value"])
        self.assertGreater(hi, res["value"])
        self.assertAlmostEqual(float(np.mean(draws)), res["value"], delta=0.01)


class TestMediumMask(unittest.TestCase):
    def test_medium_is_where_most_frames_scatter_in_the_medium(self):
        # One row of four pixels over three frames: in the medium 3/3, 2/3, 1/3 and never (no sample).
        in_medium = np.array([[1, 1, 1, 0], [1, 1, 0, 0], [1, 0, 0, 0]], bool)
        frames = []
        for m in in_medium:
            sample = np.array([[5, 6, 7, -1]])
            at_surface = ~m[None, :] & (sample >= 0)
            frames.append((sample, np.zeros_like(sample), at_surface))
        np.testing.assert_array_equal(mc.medium_mask(frames), [[True, True, False, False]])


class TestReferenceErrors(unittest.TestCase):
    def test_frames_scored_in_parallel_match_one_at_a_time(self):
        ref = 1.0 + RNG.random((48, 80))
        frames = ref + 0.3 * box_blur_wrap(RNG.standard_normal((12, 48, 80)), 2)
        regions = {"all": np.s_[:, :], "left": np.s_[:, :40]}
        one = mc.reference_errors(frames, ref, regions, workers=1)
        many = mc.reference_errors(frames, ref, regions, workers=6)
        self.assertEqual(one, many)

    def test_unbiased_frames_have_small_bias_and_known_relmse(self):
        ref = np.full((64, 64), 2.0)
        frames = ref + 0.2 * RNG.standard_normal((50, 64, 64))
        e = mc.reference_errors(frames, ref, regions={"all": np.s_[:, :]})
        self.assertLess(abs(e["regions"]["all"]["bias"]), 0.01)
        self.assertAlmostEqual(e["relmse"], (0.2 ** 2) / (4.0 + 1e-4), delta=0.002)
        self.assertLess(e["blur_rms"]["8"], e["blur_rms"]["2"])

    def test_blotchy_error_survives_blur(self):
        ref = np.full((96, 96), 1.0)
        white = ref + 0.3 * RNG.standard_normal((40, 96, 96))
        blotchy = ref + 0.3 * box_blur_wrap(RNG.standard_normal((40, 96, 96)), 4) * 9
        ew = mc.reference_errors(white, ref, regions={"all": np.s_[:, :]})
        eb = mc.reference_errors(blotchy, ref, regions={"all": np.s_[:, :]})
        self.assertGreater(eb["blur_rms"]["8"], 3 * ew["blur_rms"]["8"])


class TestCommandLine(unittest.TestCase):
    """main() on a synthetic run directory laid out the way correlation_pose.py writes one."""

    def make_run(self, root, tag, blur, ids=False, channel=None, medium_cols=None):
        import cv2
        import json
        chains = []
        name = channel or "VolumetricReSTIR.accumulated_color"
        f = 100
        noise = RNG.standard_normal((20, 60, 80))
        if blur:
            noise = box_blur_wrap(noise, 2)
        for c in range(4):
            frames = []
            for k in range(5):
                lum = 1.0 + 0.2 * noise[c * 5 + k]
                img = np.dstack([lum, lum, lum]).astype(np.float32)  # grey: luminance == value
                cv2.imwrite(os.path.join(root, "%s.%s.%d.exr" % (tag, name, f)), img)
                if ids and k == 0:
                    ident = np.zeros((60, 80, 3), np.float32)
                    ident[..., 2] = 3.0                      # every pixel holds an env sample
                    yy, xx = np.mgrid[0:60, 0:80]
                    ident[..., 0] = (yy % 10) * 100 + xx     # repeats every 10 rows: 200 per 20x20 tile
                    if medium_cols is not None:              # columns >= medium_cols: surface/background samples
                        ident[..., 1] = np.where(xx < medium_cols, 0.0, 256.0)
                    cv2.imwrite(os.path.join(root, "%s.VolumetricReSTIR.sampleIdentity.%d.exr" % (tag, f)),
                                ident[..., ::-1].copy())    # RGB -> BGR for OpenCV
                frames.append(f)
                f += 7
            chains.append({"seed": 1000 * c, "first": frames[0], "length": 30, "frames": frames})
        sched = {"scene": "synthetic", "chains": chains, "burst": None, "warm": 8, "spacing": 7}
        if channel:
            sched["channel"] = channel
        with open(os.path.join(root, tag + ".schedule.json"), "w") as fh:
            json.dump(sched, fh)

    def test_reads_the_channel_the_schedule_names(self):
        # A denoiser run captures the denoiser's output, not the estimator's.
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            self.make_run(root, "den", blur=False, channel="Denoiser.output")
            res = mc.main([root, "--tag", "den", "--bootstrap", "50", "--radii", "1", "--half", "4"])
            self.assertEqual(res["K"], 20)
            self.assertEqual(res["channel"], "Denoiser.output")
            self.assertNotIn("medium", res)  # no sampleIdentity captures, so no medium mask

    def test_medium_region_uses_the_baselines_mask(self):
        # Volume scenes: correlation inside the medium, on the no-reuse run's medium pixels, so the delta
        # compares the same pixels in both runs.
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            args = ["--bootstrap", "100", "--radii", "1,2", "--half", "4"]
            self.make_run(root, "base", blur=False, ids=True, medium_cols=30)
            base = mc.main([root, "--tag", "base"] + args)
            self.assertEqual(base["medium"]["mask"], "own")
            self.assertEqual(base["medium"]["pixels"], 60 * 30)
            self.make_run(root, "reuse", blur=True, ids=True, medium_cols=50)
            res = mc.main([root, "--tag", "reuse", "--baseline", os.path.join(root, "base.corr.json")] + args)
            self.assertEqual(res["medium"]["mask"], "baseline")
            self.assertEqual(res["medium"]["pixels"], 60 * 30)
            self.assertGreater(res["medium"]["rho"]["2"], 0.3)
            self.assertGreater(res["delta"]["medium"]["2"]["ci"][0], 0.0)
            self.assertTrue(os.path.exists(os.path.join(root, "reuse.medium.npy")))

    def test_end_to_end_with_baseline_and_identity(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            self.make_run(root, "base", blur=False)
            base = mc.main([root, "--tag", "base", "--bootstrap", "200", "--radii", "1,2,4", "--half", "6"])
            self.make_run(root, "reuse", blur=True, ids=True)
            res = mc.main([root, "--tag", "reuse", "--bootstrap", "200", "--radii", "1,2,4", "--half", "6",
                           "--baseline", os.path.join(root, "base.corr.json")])
            self.assertEqual(res["K"], 20)
            self.assertLess(abs(base["robust"]["rho"]["2"]), 0.1)
            self.assertGreater(res["robust"]["rho"]["2"], 0.3)
            d = res["delta"]["robust"]["2"]
            self.assertGreater(d["ci"][0], 0.0)          # the blurred run is more correlated, and the CI says so
            self.assertIn("autocorr", res)
            self.assertEqual(res["autocorr"]["top_offsets"][0][:2] in ([0, 1], [1, 0]), True)
            self.assertEqual(res["duplicates"]["frames"], 4)
            self.assertEqual(res["duplicates"]["sample_mean"], 200.0)
            self.assertTrue(os.path.exists(os.path.join(root, "reuse.corr.json")))


if __name__ == "__main__":
    unittest.main()
