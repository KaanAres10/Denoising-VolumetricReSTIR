import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anim_sheet as an  # noqa: E402


class TestAnimSheet(unittest.TestCase):
    def test_sheet_leads_with_the_reference_and_fills_whole_rows(self):
        tiles = [(f, np.full((512, 512, 3), 0.1 * k, np.float64)) for k, f in enumerate((5, 10, 15, 20, 25, 30, 35, 40))]
        s = an.sheet("x", tiles, size=64, cols=7)
        self.assertEqual(s.shape, (2 * 64, 7 * 64, 3))  # the reference + 8 frames: two rows of seven, the last padded
        self.assertTrue((s[64:, 2 * 64:] == 0).all())  # the padding is black
        self.assertGreater(s[:64, :64].mean(), 20)  # the reference picture, not a blank

    def test_animation_has_a_frame_per_tile(self):
        from PIL import Image
        # distinct pictures (PIL merges identical frames; at 64 px the label is cut off before the frame number)
        tiles = [(f, np.full((512, 512, 3), 0.1 * k + 0.1, np.float64)) for k, f in enumerate((5, 10, 15))]
        with tempfile.TemporaryDirectory() as t:
            path = os.path.join(t, "a.gif")
            an.gif(tiles, path, size=64)
            with Image.open(path) as im:
                self.assertEqual(im.n_frames, 3)


if __name__ == "__main__":
    unittest.main()
