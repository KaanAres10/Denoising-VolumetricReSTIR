import json
import os
import tempfile
import unittest

import numpy as np

import speed_ab_check as ab

LANE = "/onFrameRender/RenderGraphExe::execute()/VolumetricReSTIR"


def make_run(root, name, frames, total, mutate):
    d = os.path.join(root, name)
    os.makedirs(d)
    for f, img in frames.items():
        np.save(os.path.join(d, "c.VolumetricReSTIR.accumulated_color.%d.npy" % f), img)
    with open(os.path.join(d, "c.passes.json"), "w") as fh:
        json.dump({LANE + "/gpu_time": {"median": total}, LANE + "/Mutate Samples/gpu_time": {"median": mutate}}, fh)
    return d


class TestCompare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.img = np.arange(12, dtype=np.float32).reshape(2, 2, 3)

    def tearDown(self):
        self.tmp.cleanup()

    def test_identical_runs(self):
        a = make_run(self.root, "A1", {200: self.img, 208: self.img}, 10, 4)
        b = make_run(self.root, "B1", {200: self.img.copy(), 208: self.img.copy()}, 8, 2)
        c = ab.compare(a, b, ext=".npy", load=np.load)
        self.assertEqual((c["frames"], c["identical"], c["pixels_differ"]), (2, 2, 0))

    def test_one_pixel_differs(self):
        other = self.img.copy()
        other[1, 0, 2] += 1e-6
        a = make_run(self.root, "A1", {200: self.img}, 10, 4)
        b = make_run(self.root, "B1", {200: other}, 8, 2)
        c = ab.compare(a, b, ext=".npy", load=np.load)
        self.assertEqual((c["frames"], c["identical"], c["pixels_differ"]), (1, 0, 1))
        self.assertGreater(c["max_abs"], 0)

    def test_nan_in_the_same_place_counts_as_identical(self):
        img = self.img.copy()
        img[0, 0, 0] = np.nan
        a = make_run(self.root, "A1", {200: img}, 10, 4)
        b = make_run(self.root, "B1", {200: img.copy()}, 8, 2)
        self.assertEqual(ab.compare(a, b, ext=".npy", load=np.load)["identical"], 1)

    def test_a_frame_missing_on_one_side_is_not_identical(self):
        a = make_run(self.root, "A1", {200: self.img, 208: self.img}, 10, 4)
        b = make_run(self.root, "B1", {200: self.img}, 8, 2)
        c = ab.compare(a, b, ext=".npy", load=np.load)
        self.assertEqual((c["frames"], c["identical"], c["missing"]), (2, 1, 1))

    def test_against_compares_this_a1_with_the_other_b1_per_scene(self):
        other = self.img.copy()
        other[0, 1, 1] = -1
        for root, img in ((os.path.join(self.root, "new"), self.img), (os.path.join(self.root, "old"), self.img)):
            os.makedirs(os.path.join(root, "same"))
            make_run(os.path.join(root, "same"), "A1" if root.endswith("new") else "B1", {200: img}, 10, 4)
        os.makedirs(os.path.join(self.root, "new", "diff"))
        os.makedirs(os.path.join(self.root, "old", "diff"))
        make_run(os.path.join(self.root, "new", "diff"), "A1", {200: self.img}, 10, 4)
        make_run(os.path.join(self.root, "old", "diff"), "B1", {200: other}, 10, 4)
        r = ab.against(os.path.join(self.root, "new"), os.path.join(self.root, "old"), ext=".npy", load=np.load)
        self.assertEqual(r["same"]["identical"], 1)
        self.assertEqual(r["diff"]["pixels_differ"], 1)

    def test_times_average_the_two_runs_of_each_variant(self):
        for v, total, mut in (("A1", 10, 4), ("B1", 8, 2), ("B2", 6, 2), ("A2", 12, 6)):
            make_run(self.root, v, {200: self.img}, total, mut)
        t = ab.times(self.root)
        self.assertEqual((t["A"]["total"], t["B"]["total"], t["A"]["mutate"], t["B"]["mutate"]), (11, 7, 5, 2))


if __name__ == "__main__":
    unittest.main()
