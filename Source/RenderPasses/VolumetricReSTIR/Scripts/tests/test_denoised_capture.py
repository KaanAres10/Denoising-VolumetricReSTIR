"""A correlation_pose.py run with VR_DENOISER set captures the denoiser's HDR output and names it.

    VR_CORR_DEN_DIR=<dir> python -m unittest test_denoised_capture -v     (tag "d")
"""
import glob
import json
import os
import unittest

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2
import numpy as np

DIR = os.environ.get("VR_CORR_DEN_DIR", "")


class TestDenoisedCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(DIR, "d.schedule.json")) as fh:
            cls.s = json.load(fh)

    def test_schedule_names_the_denoiser_output(self):
        self.assertIn("channel", self.s)
        self.assertFalse(self.s["channel"].startswith("VolumetricReSTIR."), self.s["channel"])
        self.assertEqual(self.s["denoiser"], "optix")

    def test_denoised_frames_exist_and_are_finite_hdr(self):
        for c in self.s["chains"]:
            for f in c["frames"]:
                path, = glob.glob(os.path.join(DIR, "d.%s.%d.exr" % (self.s["channel"], f)))
                img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
                self.assertTrue(np.all(np.isfinite(img)))
                self.assertGreater(float(img.mean()), 0.0)


if __name__ == "__main__":
    unittest.main()
