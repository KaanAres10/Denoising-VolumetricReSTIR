import os
import tempfile
import unittest

import numpy as np

import chat_maps


class TestChatMaps(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3)
        self.blotch = chat_maps.band(rng.standard_normal((120, 160)) * 0.5 + 0.0, 1.0, 1e9)  # a smooth random field
        self.noise = rng.standard_normal((120, 160)) * 0.05

    def test_band_removes_the_large_scale(self):
        ramp = np.linspace(0, 10, 160)[None, :].repeat(120, 0)
        self.assertLess(np.abs(chat_maps.band(ramp, 2, 24))[30:90, 40:120].mean(), 0.05)

    def test_blotches_carried_by_c_hat_are_attributed_to_it(self):
        log_c = self.blotch * 4                       # c_hat carries the blotches
        log_r = self.noise                            # the sample part is small white noise
        s = chat_maps.split(np.exp(log_c + log_r), np.exp(log_c), np.ones(log_c.shape, bool))
        self.assertGreater(s["share_c"], 0.9)
        self.assertGreater(s["corr_c"], 0.9)

    def test_the_scene_itself_is_divided_out_by_the_reference(self):
        # The true image has structure everywhere; only the ERROR's blotches count, and here they sit in the sample part.
        scene = np.exp(self.blotch * 6)
        log_r = chat_maps.band(np.random.default_rng(5).standard_normal(scene.shape), 1.0, 1e9) * 2
        c = scene                                   # c_hat follows the true image exactly: no error in it
        s = chat_maps.split(c * np.exp(log_r), c, np.ones(scene.shape, bool), ref=scene)
        self.assertLess(s["share_c"], 0.1)
        self.assertGreater(s["corr_r"], 0.9)

    def test_blotches_carried_by_the_sample_are_attributed_to_it(self):
        log_c = self.noise
        log_r = self.blotch * 4
        s = chat_maps.split(np.exp(log_c + log_r), np.exp(log_c), np.ones(log_c.shape, bool))
        self.assertLess(s["share_c"], 0.1)


ROOT = os.path.dirname(os.path.abspath(__file__))


def png_width(path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.image
    return matplotlib.image.imread(path).shape[1]


class TestFigureWidths(unittest.TestCase):
    """Drawn at the width the paper prints them (300 dpi), so their fonts print at their sizes."""

    def test_the_c_hat_maps_fill_a_column(self):
        rng = np.random.default_rng(0)
        med = np.zeros((540, 960), bool)
        med[100:350, 280:700] = True
        maps = [(name, rng.uniform(0.2, 0.8, (540, 960, 3)), rng.uniform(0.2, 0.8, (540, 960)))
                for name in ("plain ReSTIR", "10 mutations", "decoupled history")]
        with tempfile.TemporaryDirectory() as root:
            chat_maps.figure(root, maps, np.full((540, 960), 0.5), med)
            self.assertEqual(png_width(os.path.join(root, "figs", "swarm_chat_maps.png")), 1000)  # 3.33 in

    @unittest.skipUnless(os.path.isdir(os.path.join(ROOT, chat_maps.LABEL, "den_optix_c200_m0")),
                         "needs the swarm's count runs")
    def test_the_counts_fill_the_text_width(self):
        with tempfile.TemporaryDirectory() as out:
            chat_maps.counts_denoiser_figure(ROOT, out_dir=out)
            self.assertEqual(png_width(os.path.join(out, "swarm_counts_denoisers.png")), 2100)  # 7 in


if __name__ == "__main__":
    unittest.main()
