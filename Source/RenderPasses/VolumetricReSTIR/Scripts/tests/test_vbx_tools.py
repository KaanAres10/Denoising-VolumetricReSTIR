"""vbx_tools.py: GVDB .vbx files read, written and their brick atlas widened (on a real imported volume)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import vbx_tools as vt  # noqa: E402

REPO = Path(__file__).resolve().parents[5]
SMALL = REPO / "VolumetricReSTIRData" / "bifrostfire" / "bifrostfire100" / "bifrostfire100_mip0.vbx"


def brick(v, leaf):
    """A leaf's brick (with its apron) as stored in v's atlas."""
    g = v["grid"]
    r = g["leafdim"][0] + 2 * g["apron"]
    x, y, z = (c - g["apron"] for c in vt.leaf_values(v)[leaf])
    return v["channels"][0]["atlas"][z:z + r, y:y + r, x:x + r]


@unittest.skipUnless(SMALL.exists(), "needs an imported volume")
class TestVbx(unittest.TestCase):
    def setUp(self):
        self.v = vt.read_vbx(SMALL)

    def test_reads_what_gvdb_wrote(self):
        g = self.v["grid"]
        self.assertEqual((g["leafdim"], g["apron"], g["axiscnt"][:2]), ((8, 8, 8), 1, (16, 16)))
        self.assertEqual(self.v["channels"][0]["atlas"].shape, tuple(reversed(g["axisres"])))  # z, y, x
        values = vt.leaf_values(self.v)
        self.assertEqual(len(values), g["leafcnt"])
        self.assertTrue(np.all(values % (g["leafdim"][0] + 2 * g["apron"]) == g["apron"]))  # interiors, past the apron

    def test_round_trip_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "same.vbx"
            vt.write_vbx(self.v, out)
            self.assertEqual(out.read_bytes(), SMALL.read_bytes())

    def test_widening_moves_every_brick_intact(self):
        w = vt.widen(self.v, 32, 32)
        g, h = self.v["grid"], w["grid"]
        n = g["leafcnt"]
        self.assertEqual(h["axiscnt"], (32, 32, -(-n // 1024)))
        self.assertEqual(h["axisres"], tuple(c * 10 for c in h["axiscnt"]))
        self.assertEqual(h["atlas_sz"], 4 * int(np.prod(h["axisres"])))
        self.assertEqual(vt.leaf_positions(w).tolist(), vt.leaf_positions(self.v).tolist())  # the topology is unchanged
        for leaf in range(0, n, 97):
            np.testing.assert_array_equal(brick(w, leaf), brick(self.v, leaf))
        with tempfile.TemporaryDirectory() as t:  # and survives the file
            out = Path(t) / "wide.vbx"
            vt.write_vbx(w, out)
            again = vt.read_vbx(out)
            self.assertEqual(again["grid"]["axiscnt"], h["axiscnt"])
            np.testing.assert_array_equal(brick(again, n - 1), brick(self.v, n - 1))

    def test_width_needed_keeps_small_atlases_as_they_are(self):
        self.assertEqual(vt.width_needed(3270), 16)  # fits one 2048-deep texture as imported: untouched
        self.assertEqual(vt.width_needed(16 * 16 * 204 + 1), 32)  # past one texture's depth
        self.assertEqual(vt.width_needed(32 * 32 * 204 + 1), 64)


if __name__ == "__main__":
    unittest.main()
