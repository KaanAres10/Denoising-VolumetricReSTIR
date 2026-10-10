import unittest

import numpy as np

import counts_figures


class TestCountsFigures(unittest.TestCase):
    def test_window_lands_on_the_blotchy_patch(self):
        e = np.zeros((90, 160))
        e[50:70, 100:130] = 1.0  # the only blotchy patch
        y, x = counts_figures.best_window(e, 40, 30)
        self.assertTrue(y <= 50 and y + 30 >= 70 and x <= 100 and x + 40 >= 130, (y, x))

    def test_window_stays_inside_the_image(self):
        e = np.zeros((90, 160))
        e[-1, -1] = 5.0
        y, x = counts_figures.best_window(e, 40, 30)
        self.assertEqual((y + 30 <= 90, x + 40 <= 160), (True, True))
        self.assertEqual((y, x), (60, 120))

    def test_tone_map_shares_one_scale(self):
        a = np.full((4, 4, 3), 2.0)
        out = counts_figures.tone(a, 4.0)
        self.assertTrue(np.allclose(out, 0.5 ** (1 / 2.2)))


if __name__ == "__main__":
    unittest.main()
