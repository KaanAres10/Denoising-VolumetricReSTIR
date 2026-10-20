"""medium_metrics.py and ref_change.py on synthetic runs.

    cd outputs/decorr && python -m unittest test_medium_metrics -v
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
import medium_metrics as mm
import paper_figure as pf
import ref_change

RNG = np.random.default_rng(5)
H, W = 160, 200


def write_rgb(path, rgb):
    cv2.imwrite(path, rgb[..., ::-1].astype(np.float32))


def read_rgb(path):
    return cv2.imread(path, cv2.IMREAD_UNCHANGED)[..., :3][..., ::-1].astype(np.float64)


def label_tree(root, scale_new=1.0):
    lab = os.path.join(root, "lab")
    for sub in ("ref", "ref_residual", "noreuse", "a", "b"):
        os.makedirs(os.path.join(lab, sub))
    ref = 0.4 + 0.2 * RNG.random((H, W, 3))
    for sub, s in (("ref", scale_new), ("ref_residual", 1.0)):
        write_rgb(os.path.join(lab, sub, "c.Accum.output.1023.exr"), s * ref * 1.02)
        write_rgb(os.path.join(lab, sub, "c.Accum.output.2047.exr"), s * ref)
    mask = np.zeros((H, W), bool)
    mask[30:130, 40:160] = True
    np.save(os.path.join(lab, "noreuse", "c.medium.npy"), mask)
    for cfg, noise in (("a", 0.3), ("b", 0.05)):
        with open(os.path.join(lab, cfg, "c.schedule.json"), "w") as fh:
            json.dump({"chains": [{"frames": [7]}], "channel": "VolumetricReSTIR.accumulated_color"}, fh)
        write_rgb(os.path.join(lab, cfg, "c.VolumetricReSTIR.accumulated_color.7.exr"),
                  scale_new * ref * (1 + noise * RNG.standard_normal((H, W, 1))))
    return lab, mask


class TestRelmse(unittest.TestCase):
    def test_matches_paper_figure(self):
        with tempfile.TemporaryDirectory() as root:
            lab, mask = label_tree(root)
            p = pf.prepare(root, "lab", "a", "b")
            ref = read_rgb(os.path.join(lab, "ref", "c.Accum.output.2047.exr"))
            for cfg, cropped in zip(("a", "b"), p.imgs):
                full = read_rgb(os.path.join(lab, cfg, "c.VolumetricReSTIR.accumulated_color.7.exr"))
                self.assertAlmostEqual(mm.relmse(full, ref, mask), p.relmse(cropped), places=9)

    def test_size_mismatch_raises(self):
        mask = np.ones((10, 12), bool)
        with self.assertRaises(ValueError):
            mm.relmse(np.ones((10, 10, 3)), np.ones((10, 12, 3)), mask)
        with self.assertRaises(ValueError):
            mm.relmse(np.ones((10, 12, 3)), np.ones((10, 12, 3)), np.ones((10, 10), bool))

    def test_brightness(self):
        ref = 0.5 + RNG.random((8, 9, 3))
        mask = np.ones((8, 9), bool)
        self.assertAlmostEqual(mm.brightness(1.1 * ref, ref, mask), 1.1, places=9)

    def test_accumulations_need_two_files(self):
        with tempfile.TemporaryDirectory() as root:
            write_rgb(os.path.join(root, "c.Accum.output.2047.exr"), np.ones((4, 4, 3)))
            with self.assertRaises(FileNotFoundError):
                mm.accumulations(root)


class TestRefChange(unittest.TestCase):
    def test_a_brighter_new_reference(self):
        with tempfile.TemporaryDirectory() as root:
            label_tree(root, scale_new=1.05)
            c = ref_change.change(root, "lab")
            self.assertAlmostEqual(c["mean_ratio"], 1.05, places=4)
            self.assertGreater(c["relmse_old_vs_new"], 0.0)
            self.assertAlmostEqual(c["own_relmse_new"], c["own_relmse_old"], places=6)

    def test_a_missing_old_reference_raises(self):
        with tempfile.TemporaryDirectory() as root:
            lab, _ = label_tree(root)
            for f in os.listdir(os.path.join(lab, "ref_residual")):
                os.rename(os.path.join(lab, "ref_residual", f), os.path.join(lab, f))
            with self.assertRaises(FileNotFoundError):
                ref_change.change(root, "lab")


if __name__ == "__main__":
    unittest.main()
