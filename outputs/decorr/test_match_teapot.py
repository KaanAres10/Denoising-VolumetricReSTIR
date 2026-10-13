import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import match_teapot as mt  # noqa: E402


class TestMatchTeapot(unittest.TestCase):
    def test_standard_view_is_srgb_clipped(self):
        v = mt.standard_view(np.array([0.0, 0.002, 0.5, 1.0, 7.0]))
        np.testing.assert_allclose(v, [0.0, 0.002 * 12.92, 1.055 * 0.5 ** (1 / 2.4) - 0.055, 1.0, 1.0], rtol=1e-9)

    def test_hdr_capture_takes_the_high_exposure_where_the_low_one_clips(self):
        with tempfile.TemporaryDirectory() as t:
            stem = os.path.join(t, "x")
            lo = np.zeros((1, 2, 3), np.uint16)
            hi = np.zeros((1, 2, 3), np.uint16)
            lo[0, 0], hi[0, 0] = 32768, 32  # 0.5: from the low exposure
            lo[0, 1], hi[0, 1] = 65535, 6400  # clipped: 6400 / 65535 x 1024 = 100
            cv2.imwrite(stem + "_lo.png", lo)
            cv2.imwrite(stem + "_hi.png", hi)
            img = mt.read_rman(stem)
        np.testing.assert_allclose(img[0, 0], 32768 / 65535, rtol=1e-9)
        np.testing.assert_allclose(img[0, 1], 6400 / 65535 * 1024, rtol=1e-9)


if __name__ == "__main__":
    unittest.main()
