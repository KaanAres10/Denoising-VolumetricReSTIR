import json
import os
import tempfile
import unittest

import numpy as np

import bias_summary

RNG = np.random.default_rng(7)


def chains(level, n=64, noise=0.01, shared=None):
    shared = RNG.standard_normal((n, 3)) * noise if shared is None else shared
    return (np.array(level) + shared).tolist(), shared


class TestBiasSummary(unittest.TestCase):
    def test_luminance_weights_rec709(self):
        np.testing.assert_allclose(bias_summary.luminance(np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])),
                                   [0.2126, 0.7152, 0.0722])

    def test_unbiased_pair_has_a_small_z(self):
        base, shared = chains([0.5, 0.5, 0.5])
        conf, _ = chains([0.5, 0.5, 0.5], shared=shared + RNG.standard_normal((64, 3)) * 0.001)
        z = bias_summary.setup_z({"plain": base, "mut5": conf})
        self.assertLess(abs(z["lum"][2]), 4.0)

    def test_a_one_percent_bias_is_many_standard_errors(self):
        base, shared = chains([0.5, 0.5, 0.5])
        conf, _ = chains([0.505, 0.505, 0.505], shared=shared + RNG.standard_normal((64, 3)) * 0.0005)
        z = bias_summary.setup_z({"plain": base, "mut5": conf})
        self.assertAlmostEqual(z["lum"][0], 0.01, places=3)
        self.assertGreater(z["lum"][2], 10.0)

    def test_chi_square_survival_known_values(self):
        self.assertAlmostEqual(bias_summary.chi2_sf(10.0, 10), 0.4405, places=3)
        self.assertAlmostEqual(bias_summary.chi2_sf(0.0, 10), 1.0)
        self.assertAlmostEqual(bias_summary.chi2_sf(23.21, 10), 0.01, places=3)

    def test_reads_every_setups_chains(self):
        with tempfile.TemporaryDirectory() as root:
            for label in ("a", "b_b2"):
                os.makedirs(os.path.join(root, label))
                base, shared = chains([0.4, 0.5, 0.6])
                with open(os.path.join(root, label, "chains.json"), "w") as fh:
                    json.dump({"plain": base, "mut5": (np.array(base) * 1.0).tolist()}, fh)
            rows = bias_summary.rows(root)
        self.assertEqual([r[0] for r in rows], ["a", "b_b2"])


if __name__ == "__main__":
    unittest.main()
