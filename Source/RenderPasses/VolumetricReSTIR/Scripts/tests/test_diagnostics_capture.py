"""Checks the captures check_diagnostics.py writes (run that under Mogwai first).

    VR_DIAG_DIR=<dir> python -m unittest test_diagnostics_capture.py -v
"""
import glob
import json
import os
import unittest

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2
import numpy as np

DIR = os.environ.get("VR_DIAG_DIR", "")


def load(channel, frame):
    paths = glob.glob(os.path.join(DIR, "diag.VolumetricReSTIR.%s.%d.exr" % (channel, frame)))
    if not paths:
        raise AssertionError("missing capture: %s frame %d in %s" % (channel, frame, DIR))
    img = cv2.imread(paths[0], cv2.IMREAD_UNCHANGED)
    if img is None:
        raise AssertionError("unreadable capture: " + paths[0])
    return img


def rgba(channel, frame):
    """The capture in RGBA order (OpenCV reads EXR as BGR(A))."""
    img = load(channel, frame)
    if img.shape[2] == 4:
        b, g, r, a = cv2.split(img)
        return np.dstack([r, g, b, a])
    b, g, r = cv2.split(img)
    return np.dstack([r, g, b])


class TestDiagnosticsCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        meta = os.path.join(DIR, "diag.frames.json")
        if not DIR or not os.path.exists(meta):
            raise AssertionError("no diag.frames.json in VR_DIAG_DIR=%r (run check_diagnostics.py)" % DIR)
        with open(meta) as fh:
            cls.frames = json.load(fh)["frames"]

    def test_same_seed_replays_exactly(self):
        a = load("accumulated_color", self.frames[0])
        a2 = load("accumulated_color", self.frames[2])
        self.assertTrue(np.array_equal(a, a2), "seed 1000 twice gave different frames")

    def test_different_seed_differs(self):
        a = load("accumulated_color", self.frames[0])
        b = load("accumulated_color", self.frames[1])
        self.assertFalse(np.array_equal(a, b), "seeds 1000 and 2000 gave the same frame")

    def test_identity_channel_is_well_formed(self):
        # Frame capture writes RGB only (alpha is dropped), so validity is carried by .z:
        # lightID >= -3 makes .z = lightID + 4 >= 1 for every sample, and .z = 0 means none.
        idn = rgba("sampleIdentity", self.frames[0])
        x, y, z = (idn[..., i] for i in range(3))
        valid = z > 0
        self.assertGreater(valid.mean(), 0.3, "plume: most pixels hold a sample")
        for c in (x, y, z):
            self.assertTrue(np.all(c == np.floor(c)), "identity values are integers")
        self.assertTrue(np.all(x[valid] < 2 ** 24) and np.all(y[valid] < 256))
        self.assertTrue(np.all(x[~valid] == 0) and np.all(z[~valid] == 0))
        # Plume is env-lit and volume-only: lightID -1 for an env light sample, and 0 for a background
        # sample (ComputeInitialSample leaves createNewReservoir's lightID 0 there; only surface scenes
        # tag it kSelfEmissionLightID) -> z in {3, 4}.
        self.assertTrue(set(np.unique(z[valid])).issubset({3.0, 4.0}), np.unique(z[valid]))
        # Distinct samples are the norm on a single frame after 6 frames of reuse, not one repeated id.
        ids = x[valid].astype(np.int64) | (y[valid].astype(np.int64) << 24)
        self.assertGreater(len(np.unique(ids)), 0.05 * valid.sum())


if __name__ == "__main__":
    unittest.main()
