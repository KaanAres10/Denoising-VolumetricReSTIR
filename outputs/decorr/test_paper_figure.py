"""paper_figure.pick_boxes on synthetic frames.

    cd outputs/decorr && python -m unittest test_paper_figure -v
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_figure as pf


def two_blotches():
    """A flat reference and a frame darker in two wide patches (darker: pick_boxes clips brightness at the
    reference's 99.5%), the first the stronger."""
    ref = np.full((120, 200, 3), 0.5)
    a = ref.copy()
    a[20:40, 30:70] -= 0.3
    a[80:100, 120:160] -= 0.2
    return a, ref


class TestPickBoxes(unittest.TestCase):
    def test_wide_windows_land_on_the_two_blotches_strongest_first(self):
        a, ref = two_blotches()
        (y0, x0), (y1, x1) = pf.pick_boxes(a, ref, 20, n=2, width=40)
        self.assertLessEqual(max(abs(y0 - 20), abs(x0 - 30)), 3)  # a 20 x 40 window over the patch at 20:40, 30:70
        self.assertLessEqual(max(abs(y1 - 80), abs(x1 - 120)), 3)

    def test_square_by_default(self):
        a, ref = two_blotches()
        self.assertEqual(pf.pick_boxes(a, ref, 20, n=2), pf.pick_boxes(a, ref, 20, n=2, width=20))


if __name__ == "__main__":
    unittest.main()
