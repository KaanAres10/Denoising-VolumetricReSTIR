"""Every study scene renders: smoke_scene.py's capture per scene is present, finite and not black.

    VR_SMOKE_DIR=<dir holding one sub-directory per scene> python -m unittest test_smoke_scenes -v
"""
import glob
import os
import unittest

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2
import numpy as np

SCENES = ("plume", "bistro", "explosion", "emerald", "bunny", "wdas")
ROOT = os.environ.get("VR_SMOKE_DIR", "")


class TestSmokeScenes(unittest.TestCase):
    def test_every_scene_renders_a_lit_frame(self):
        for name in SCENES:
            with self.subTest(scene=name):
                paths = glob.glob(os.path.join(ROOT, name, name + ".*.accumulated_color.*.exr"))
                self.assertEqual(len(paths), 1, "no capture for " + name)
                img = cv2.imread(paths[0], cv2.IMREAD_UNCHANGED).astype(np.float64)
                self.assertTrue(np.all(np.isfinite(img)), name)
                lit = (img[..., :3].max(axis=2) > 0).mean()
                self.assertGreater(lit, 0.05, "%s: %.1f%% lit pixels" % (name, 100 * lit))


if __name__ == "__main__":
    unittest.main()
