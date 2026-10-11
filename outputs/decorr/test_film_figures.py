import os
import tempfile
import unittest

import numpy as np

import film_figures


class TestFilmFigures(unittest.TestCase):
    def test_noise_floor_estimates_the_full_references_own_error(self):
        # A reference of 2N frames and its first N: the half-vs-full error is the full reference's error vs the truth.
        rng = np.random.default_rng(3)
        truth = 1.0 + rng.random(20000)
        frames = truth + rng.normal(0, 4.0, (256, truth.size))
        half, full = frames[:128].mean(0), frames.mean(0)
        relmse = lambda img: float(np.mean((img - full) ** 2) / np.mean(full ** 2))  # noqa: E731
        own = float(np.mean((full - truth) ** 2) / np.mean(truth ** 2))
        self.assertAlmostEqual(film_figures.noise_floor(relmse, half) / own, 1.0, delta=0.05)

    def test_half_reference_is_the_earlier_accumulation(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "shot", "ref"))
            for n in (2047, 1023):
                open(os.path.join(root, "shot", "ref", "c.Accum.output.%d.exr" % n), "w").close()
            self.assertEqual(os.path.basename(film_figures.half_reference_path(root, "shot")), "c.Accum.output.1023.exr")

    def test_half_reference_needs_two_accumulations(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "shot", "ref"))
            open(os.path.join(root, "shot", "ref", "c.Accum.output.2047.exr"), "w").close()
            self.assertIsNone(film_figures.half_reference_path(root, "shot"))

    def test_display_keeps_a_bright_tiles_hue(self):
        tile = np.array([[[6.0, 0.6, 3.6]]])  # an LED tile far above the exposure
        out = film_figures.display(tile, 0.68) ** 2.2
        self.assertTrue(np.allclose(out[0, 0] / out[0, 0].max(), [1.0, 0.1, 0.6], atol=1e-6), out)

    def test_display_rolls_off_without_clipping(self):
        grey = np.array([[[0.68] * 3, [6.8] * 3, [680.0] * 3]])
        out = film_figures.display(grey, 0.68)[0, :, 0] ** 2.2
        self.assertTrue(np.allclose(out, [0.5, 10 / 11, 1000 / 1001]), out)  # t / (1 + t): a flash still has shading

    def test_exposure_ignores_a_bright_flash(self):
        y = np.ones((50, 20))
        y[:10] = 1000.0  # a fifth of the crop: a lightning flash
        k = film_figures.exposure(y, np.ones_like(y, bool))
        self.assertAlmostEqual(k * film_figures.EXPOSURE_KEY, 1.0, places=6)

    def test_exposure_reads_only_the_medium(self):
        y = np.full((20, 20), 4.0)
        med = np.zeros_like(y, bool)
        y[:10] = 0.5
        med[:10] = True  # the fog is the dim half; the bright half is a building
        self.assertAlmostEqual(film_figures.exposure(y, med) * film_figures.EXPOSURE_KEY, 0.5, places=6)

    def test_chain_label_gives_the_mean_and_the_range(self):
        self.assertEqual(film_figures.score_label([0.0223, 0.0182], 1.024), "relMSE 0.020 (0.018-0.022) · mean 1.02x")


if __name__ == "__main__":
    unittest.main()
