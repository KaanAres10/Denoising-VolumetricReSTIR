"""A small correlation_pose.py run (2 chains x 2 captures, VR_IDS=1) wrote what the metrics expect.

    VR_CORR_DIR=<dir> VR_CORR_TAG=<tag> python -m unittest test_correlation_capture -v
"""
import glob
import json
import os
import unittest

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2
import numpy as np

DIR = os.environ.get("VR_CORR_DIR", "")
TAG = os.environ.get("VR_CORR_TAG", "t")


def exr(channel, frame):
    path, = glob.glob(os.path.join(DIR, "%s.VolumetricReSTIR.%s.%d.exr" % (TAG, channel, frame)))
    return cv2.imread(path, cv2.IMREAD_UNCHANGED)


class TestCorrelationCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(DIR, TAG + ".schedule.json")) as fh:
            cls.s = json.load(fh)

    def test_schedule_records_the_chains(self):
        self.assertEqual(len(self.s["chains"]), 2)
        self.assertEqual([len(c["frames"]) for c in self.s["chains"]], [2, 2])
        self.assertEqual(self.s["scene"], "plume")
        seeds = [c["seed"] for c in self.s["chains"]]
        self.assertEqual(len(set(seeds)), 2)

    def test_every_scheduled_frame_was_captured_in_both_channels(self):
        for c in self.s["chains"]:
            for f in c["frames"]:
                for channel in ("accumulated_color", "sampleIdentity"):
                    self.assertIsNotNone(exr(channel, f), (channel, f))

    def test_chains_are_distinct_realizations(self):
        a, b = (exr("accumulated_color", c["frames"][0]) for c in self.s["chains"])
        self.assertFalse(np.array_equal(a, b))

    def test_frames_within_a_chain_differ(self):
        f = self.s["chains"][0]["frames"]
        self.assertFalse(np.array_equal(exr("accumulated_color", f[0]), exr("accumulated_color", f[1])))


if __name__ == "__main__":
    unittest.main()
