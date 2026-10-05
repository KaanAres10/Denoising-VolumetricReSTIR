"""bias_check.py: per-channel mean of a config against a baseline, with chain-level error bars.

    python -m unittest test_bias_check -v
"""
import unittest

import numpy as np

import bias_check

RNG = np.random.default_rng(7)


class TestRelativeBias(unittest.TestCase):
    def test_recovers_a_known_offset(self):
        base = 2.0 + 0.01 * RNG.standard_normal((40, 3))
        conf = 2.0 * np.array([1.0, 0.99, 1.02]) + 0.01 * RNG.standard_normal((40, 3))
        bias, se = bias_check.relative_bias(conf, base)
        np.testing.assert_allclose(bias, [0.0, -0.01, 0.02], atol=4 * se.max())
        self.assertTrue(np.all(se < 0.002))

    def test_error_bar_counts_chains_not_frames(self):
        # Each chain's frames share one offset: the spread of chain means, not of frames, sets the error bar.
        chains = [list(range(10 * c, 10 * c + 10)) for c in range(4)]
        offsets = [0.1, -0.1, 0.05, -0.05]
        frames = {f: np.full(3, 1.0 + offsets[c]) for c, fs in enumerate(chains) for f in fs}
        m = bias_check.chain_means(frames, chains)
        self.assertEqual(m.shape, (4, 3))
        np.testing.assert_allclose(m[:, 0], 1.0 + np.array(offsets))

    def test_paired_error_bar_cancels_the_shared_chain_noise(self):
        # Configs whose chain i shares chain i's seeds (correlation_pose.py: VR_SEED_BASE + i * stride) carry the same
        # chain noise; the unpaired error bar counts it twice, the paired one cancels it (final review, 2026-10-06).
        n = 64
        shared = 0.05 * RNG.standard_normal((n, 1))
        base = 2.0 * (1.0 + shared) * np.ones((n, 3))
        conf = base * np.array([1.0, 1.003, 0.997]) + 0.002 * RNG.standard_normal((n, 3))
        bias_u, se_u = bias_check.relative_bias(conf, base)
        bias_p, se_p = bias_check.paired_relative_bias(conf, base)
        np.testing.assert_allclose(bias_p, bias_u)  # the same estimate, a different error bar
        np.testing.assert_allclose(bias_p, [0.0, 0.003, -0.003], atol=4 * se_p.max())
        self.assertTrue(np.all(se_p < 0.0005))
        self.assertTrue(np.all(se_u > 10 * se_p))

    def test_paired_needs_the_same_chains(self):
        with self.assertRaises(ValueError):
            bias_check.paired_relative_bias(np.ones((4, 3)), np.ones((5, 3)))

    def test_reference_bias(self):
        # A config's mean against a converged reference's: the error bar is the config's chain spread alone.
        conf = 0.5 * np.array([1.0, 1.01, 0.98]) + 0.001 * RNG.standard_normal((50, 3))
        bias, se = bias_check.reference_bias(conf, np.array([0.5, 0.5, 0.5]))
        np.testing.assert_allclose(bias, [0.0, 0.01, -0.02], atol=4 * se.max())
        np.testing.assert_allclose(se, conf.std(0, ddof=1) / np.sqrt(50) / 0.5)

    def test_missing_frames_are_skipped(self):
        chains = [[1, 2, 3], [4, 5]]
        frames = {1: np.ones(3), 3: 3 * np.ones(3), 4: 2 * np.ones(3)}
        np.testing.assert_allclose(bias_check.chain_means(frames, chains), [[2, 2, 2], [2, 2, 2]])


if __name__ == "__main__":
    unittest.main()
