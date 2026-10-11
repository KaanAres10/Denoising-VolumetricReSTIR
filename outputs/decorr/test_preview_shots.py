import unittest

import numpy as np

import preview_shots as ps


class TestLens(unittest.TestCase):
    CAM = dict(position=(0.0, 10.0, 10.0), target=(0.0, 0.0, 0.0), focal_mm=50.0)

    def test_plane_depth_at_the_centre_pixel(self):
        # the centre pixel's ray runs from the camera to its target, which lies on the plane y = 0
        d = ps.plane_depth((101, 181), plane_y=0.0, **self.CAM)
        self.assertAlmostEqual(float(d[50, 90]), np.sqrt(200.0), places=3)
        self.assertGreater(d[0, 90], d[100, 90])  # the top of the frame looks farther

    def test_lens_blur_keeps_the_focus_plane_sharp_and_softens_the_rest(self):
        rng = np.random.default_rng(1)
        img = rng.random((101, 181, 3)).astype(np.float32)
        out = ps.lens_blur(img, focus=np.sqrt(200.0), max_blur=4.0, plane_y=0.0, **self.CAM)
        self.assertTrue(np.allclose(out[50, 80:100], img[50, 80:100], atol=0.05))  # the focus row: unchanged
        self.assertLess(out[:8].std(), 0.6 * img[:8].std())  # the far top rows: softened
        self.assertEqual(out.shape, img.shape)


if __name__ == "__main__":
    unittest.main()
