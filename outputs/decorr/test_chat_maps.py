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


if __name__ == "__main__":
    unittest.main()
