"""motion_score.py on a synthetic construct run tree.

    cd outputs/decorr && python -m unittest test_motion_score -v
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
import motion_score as ms

RNG = np.random.default_rng(5)
H, W = 30, 50
CHANNELS = {"optix": "OptiXDenoiser.output", "rr": "DLSSDPass.output", "raw": "VolumetricReSTIR.accumulated_color"}


def write_rgb(path, rgb):
    cv2.imwrite(path, rgb[..., ::-1].astype(np.float32))


def tree(root):
    lab = os.path.join(root, ms.LABEL)
    os.makedirs(os.path.join(lab, "ref"))
    os.makedirs(os.path.join(lab, "noreuse"))
    ref = 0.4 + 0.2 * RNG.random((H, W, 3))
    write_rgb(os.path.join(lab, "ref", "c.Accum.output.1.exr"), ref * 1.02)
    write_rgb(os.path.join(lab, "ref", "c.Accum.output.3.exr"), ref)
    mask = np.zeros((H, W), bool)
    mask[4:26, 5:45] = True
    np.save(os.path.join(lab, "noreuse", "c.medium.npy"), mask)
    imgs = {}
    for name, ch in CHANNELS.items():
        for m, noise in ((0, 0.3), (5, 0.1)):
            d = os.path.join(lab, "cam7_%s_m%d" % (name, m))
            os.makedirs(d)
            with open(os.path.join(d, "c.schedule.json"), "w") as fh:
                json.dump({"channel": ch, "chains": [{"frames": [7]}]}, fh)
            img = ref * (1 + noise * RNG.standard_normal((H, W, 1)))
            write_rgb(os.path.join(d, "c.%s.7.exr" % ch), img)
            imgs[(name, m)] = img.astype(np.float32).astype(np.float64)
    return ref.astype(np.float32).astype(np.float64), mask, imgs


class TestMotionScore(unittest.TestCase):
    def test_each_output_plain_against_mutated(self):
        with tempfile.TemporaryDirectory() as root:
            ref, mask, imgs = tree(root)
            out_path = os.path.join(root, "motion.json")
            out = ms.main([root, "--out", out_path])
            self.assertEqual(set(out), {"optix", "rr", "raw"})
            for name in out:
                self.assertAlmostEqual(out[name]["m0"], mm.relmse(imgs[(name, 0)], ref, mask), places=9)
                self.assertLess(out[name]["m5"], out[name]["m0"])
                self.assertAlmostEqual(out[name]["change"], out[name]["m5"] / out[name]["m0"] - 1, places=12)
                self.assertIn("brightness_m5", out[name])
            with open(out_path) as fh:
                self.assertEqual(json.load(fh)["rr"]["m5"], out["rr"]["m5"])


if __name__ == "__main__":
    unittest.main()
