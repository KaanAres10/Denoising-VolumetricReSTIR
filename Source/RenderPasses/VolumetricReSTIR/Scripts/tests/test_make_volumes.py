"""make_volumes.py: the authored volumes' density fields and their raw layout (no tools run).

    python -m unittest test_make_volumes -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import make_volumes as mv  # noqa: E402
import volume_boxes as vb  # noqa: E402

COARSE = 0.5  # metres per voxel: the fields' shape, not their detail, at test speed


class TestNoise(unittest.TestCase):
    def test_fbm_is_in_unit_range_and_deterministic(self):
        a = mv.fbm((40, 30, 20), cell=8, octaves=3, seed=5)
        self.assertEqual(a.shape, (40, 30, 20))
        self.assertTrue(0.0 <= a.min() and a.max() <= 1.0)
        self.assertTrue(np.array_equal(a, mv.fbm((40, 30, 20), cell=8, octaves=3, seed=5)))
        self.assertFalse(np.array_equal(a, mv.fbm((40, 30, 20), cell=8, octaves=3, seed=6)))

    def test_fbm_is_smooth_at_its_cell_size(self):
        a = mv.fbm((64, 64, 64), cell=16, octaves=1, seed=1)
        step = np.abs(np.diff(a, axis=0)).mean()
        self.assertLess(step, 0.05 * (a.max() - a.min()))  # white noise would step ~0.33 of its range


class TestFields(unittest.TestCase):
    def test_box_dims(self):
        self.assertEqual(vb.dims("stagehaze"), (260, 100, 220))

    def test_stage_haze_fades_at_the_sides_and_sits_low(self):
        d = mv.stage_haze(voxel=COARSE)
        self.assertEqual(d.shape, mv.shape("stagehaze", COARSE))
        self.assertTrue(0.0 <= d.min() and d.max() <= 1.0)
        for face in (d[0], d[-1], d[:, :, -1]):  # left, right and audience sides: no hard wall of haze
            self.assertLess(face.max(), 1e-3)
        self.assertLess(d[:, -1].max(), 1e-3)  # nor a ceiling
        self.assertGreater(d[:, 2:6].mean(), 1.2 * d[:, 12:16].mean())  # floor (1-3 m) denser than 6-8 m
        self.assertGreater(d.mean(), 0.1)

    def test_ground_mist_hugs_the_ground_and_fades_out_far_away(self):
        d = mv.ground_mist(voxel=COARSE)
        self.assertTrue(0.0 <= d.min() and d.max() <= 1.0)
        self.assertGreater(d[:, :2].mean(), 4 * d[:, 10:].mean())  # below 1 m vs above 5 m
        self.assertLess(d[0].max() + d[-1].max() + d[:, :, 0].max() + d[:, :, -1].max(), 1e-3)
        self.assertGreater(d[:, :2].mean(), 0.05)

    def test_smoke_puffs_sit_on_the_bursts(self):
        d = mv.smoke_puffs(voxel=COARSE)
        lo, _, _ = vb.BOXES["smokepuffs"]
        for c, _ in vb.BURSTS:
            i, j, k = (int((c[a] - lo[a]) / COARSE) for a in range(3))
            self.assertGreater(d[i - 2:i + 3, j - 2:j + 3, k - 2:k + 3].mean(), 0.2, c)
        self.assertLess(d[:4, -4:].max(), 0.05)  # the box's far corner: clear air
        self.assertTrue(0.0 <= d.min() and d.max() <= 1.0)


class TestRaw(unittest.TestCase):
    def test_raw_is_x_slowest(self):
        # VolFromRaw reads data[(i * ny + j) * nz + k] as voxel (i, j, k)
        a = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "a.raw")
            mv.write_raw(a, p)
            flat = np.fromfile(p, dtype=np.float32)
        self.assertEqual(flat[(1 * 3 + 2) * 4 + 3], a[1, 2, 3])
        self.assertEqual(flat.size, 24)


if __name__ == "__main__":
    unittest.main()
