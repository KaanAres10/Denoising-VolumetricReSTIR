"""five_scores.py on a synthetic run tree.

    cd outputs/decorr && python -m unittest test_five_scores -v
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
import five_scores as fs
import medium_metrics as mm

RNG = np.random.default_rng(3)
H, W = 40, 60
SHARED = {"optix": "D_optix_Denoiser.output", "raw": "VolumetricReSTIR.accumulated_color"}


def write_rgb(path, rgb):
    cv2.imwrite(path, rgb[..., ::-1].astype(np.float32))


def as32(x):
    return x.astype(np.float32).astype(np.float64)


def tree(root):
    lab = os.path.join(root, "bunnyspot")
    os.makedirs(os.path.join(lab, "ref"))
    os.makedirs(os.path.join(lab, "noreuse"))
    ref = 0.5 + 0.1 * RNG.random((H, W, 3))
    write_rgb(os.path.join(lab, "ref", "c.Accum.output.1.exr"), ref * 1.01)
    write_rgb(os.path.join(lab, "ref", "c.Accum.output.3.exr"), ref)
    mask = np.zeros((H, W), bool)
    mask[5:35, 10:50] = True
    np.save(os.path.join(lab, "noreuse", "c.medium.npy"), mask)
    imgs = {}
    for cfg in ("fd_c200_m0", "fd_c200_m5", "fr_c200_m0", "fr_c200_m5"):
        d = os.path.join(lab, cfg)
        os.makedirs(d)
        chans = SHARED if cfg.startswith("fd") else {"rr": "DLSSDPass.output"}
        sched = {"chains": [{"frames": [10]}, {"frames": [20]}],
                 "channel": "VolumetricReSTIR.accumulated_color" if cfg.startswith("fd") else "DLSSDPass.output"}
        if cfg.startswith("fd"):
            sched["channels"] = SHARED
        with open(os.path.join(d, "c.schedule.json"), "w") as fh:
            json.dump(sched, fh)
        for name, ch in chans.items():
            for f in (10, 20):
                img = ref * (1 + (0.2 if cfg.endswith("m0") else 0.05) * RNG.standard_normal((H, W, 1)))
                write_rgb(os.path.join(d, "c.%s.%d.exr" % (ch, f)), img)
                imgs[(cfg, name, f)] = img
    return lab, as32(ref), mask, imgs


class TestScore(unittest.TestCase):
    def test_every_channel_scored_on_both_kept_frames(self):
        with tempfile.TemporaryDirectory() as root:
            _, ref, mask, imgs = tree(root)
            c = fs.score(root, "bunnyspot")["histories"]["c200"]
            self.assertEqual(set(c["m0"]), {"optix", "raw", "rr"})
            want = np.mean([mm.relmse(as32(imgs[("fd_c200_m5", "optix", f)]), ref, mask) for f in (10, 20)])
            self.assertAlmostEqual(c["m5"]["optix"]["mean"], want, places=9)
            self.assertLess(c["m5"]["rr"]["mean"], c["m0"]["rr"]["mean"])
            self.assertEqual(c["m0"]["rr"]["run"], "bunnyspot/fr_c200_m0")
            self.assertEqual(len(c["m5"]["raw"]["brightness"]), 2)

    def test_a_missing_frame_raises(self):
        with tempfile.TemporaryDirectory() as root:
            lab, _, _, _ = tree(root)
            os.rename(os.path.join(lab, "fr_c200_m5", "c.DLSSDPass.output.20.exr"), os.path.join(lab, "moved.exr"))
            with self.assertRaises(FileNotFoundError):
                fs.score(root, "bunnyspot")


if __name__ == "__main__":
    unittest.main()
