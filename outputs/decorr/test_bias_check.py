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

    def test_missing_frames_are_skipped(self):
        chains = [[1, 2, 3], [4, 5]]
        frames = {1: np.ones(3), 3: 3 * np.ones(3), 4: 2 * np.ones(3)}
        np.testing.assert_allclose(bias_check.chain_means(frames, chains), [[2, 2, 2], [2, 2, 2]])


if __name__ == "__main__":
    unittest.main()
