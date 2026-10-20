"""five_gate.py: one run's channel against another's, frame by frame.

    cd outputs/decorr && python -m unittest test_five_gate -v
"""
import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import five_gate


def run(root, name, channel, images, frames=(3, 8)):
    d = os.path.join(root, name)
    os.makedirs(d)
    with open(os.path.join(d, "c.schedule.json"), "w") as fh:
        json.dump({"chains": [{"frames": [f]} for f in frames]}, fh)
    for f, img in zip(frames, images):
        cv2.imwrite(os.path.join(d, "c.%s.%d.exr" % (channel, f)), img.astype(np.float32))
    return d


class TestCompare(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.img = np.random.default_rng(1).random((6, 5, 3))

    def test_identical_frames(self):
        a = run(self.root, "a", "X.out", [self.img, self.img])
        b = run(self.root, "b", "Y.out", [self.img, self.img])
        self.assertEqual(five_gate.compare(a, "X.out", b, "Y.out"),
                         {"frames": 2, "identical": 2, "max_abs": 0.0, "mean_abs": 0.0})

    def test_a_changed_pixel(self):
        other = self.img.copy()
        other[2, 2, 1] += 0.5
        a = run(self.root, "a", "X.out", [self.img, self.img])
        b = run(self.root, "b", "X.out", [self.img, other])
        r = five_gate.compare(a, "X.out", b, "X.out")
        self.assertEqual(r["identical"], 1)
        self.assertAlmostEqual(r["max_abs"], 0.5, places=5)

    def test_different_frames_or_sizes_raise(self):
        a = run(self.root, "a", "X.out", [self.img, self.img])
        b = run(self.root, "b", "X.out", [self.img, self.img], frames=(3, 9))
        with self.assertRaises(ValueError):
            five_gate.compare(a, "X.out", b, "X.out")
        c = run(self.root, "c", "X.out", [self.img[:4], self.img[:4]])
        with self.assertRaises(ValueError):
            five_gate.compare(a, "X.out", c, "X.out")


if __name__ == "__main__":
    unittest.main()
