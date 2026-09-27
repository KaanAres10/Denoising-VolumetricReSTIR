"""VR_SR_PER_PIXEL_OFFSETS: check_diagnostics.py captured once with the define and once without.

    VR_DIAG_DIR=<default run> VR_DIAG_OFFSETS_DIR=<run with VR_SLANG_ARGS=-DVR_SR_PER_PIXEL_OFFSETS=1> \
        python -m unittest test_offsets_capture -v
"""
import glob
import json
import os
import unittest

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2
import numpy as np


def frame(run_dir, index):
    with open(os.path.join(run_dir, "diag.frames.json")) as fh:
        f = json.load(fh)["frames"][index]
    path, = glob.glob(os.path.join(run_dir, "diag.VolumetricReSTIR.accumulated_color.%d.exr" % f))
    return cv2.imread(path, cv2.IMREAD_UNCHANGED).astype(np.float64)


class TestPerPixelOffsets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.off = frame(os.environ["VR_DIAG_DIR"], 0)
        cls.on = frame(os.environ["VR_DIAG_OFFSETS_DIR"], 0)

    def test_the_define_changes_the_neighbours(self):
        self.assertFalse(np.array_equal(self.off, self.on))

    def test_output_stays_finite_and_non_negative(self):
        self.assertTrue(np.all(np.isfinite(self.on)))
        self.assertGreaterEqual(self.on.min(), 0.0)

    def test_mean_level_is_comparable(self):
        # A sanity bound, not an unbiasedness test: one frame of a different neighbour pattern.
        ratio = self.on.mean() / self.off.mean()
        self.assertTrue(0.8 < ratio < 1.25, ratio)


if __name__ == "__main__":
    unittest.main()
