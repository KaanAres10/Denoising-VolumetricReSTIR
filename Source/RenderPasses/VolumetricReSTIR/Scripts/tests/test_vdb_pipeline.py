import sys, unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
REPO = SCRIPTS.parents[3]
DATA = REPO / "VolumetricReSTIRData"

import vdb_pipeline as vp


class TestReadBakedHeader(unittest.TestCase):
    """Asserted against real baked files already in VolumetricReSTIRData."""

    def test_reads_fire115_which_has_velocity(self):
        h = vp.read_baked_header(DATA / "fire115" / "fire115.0100.bin")
        self.assertEqual(h.num_mips, 4)
        self.assertTrue(h.has_velocity)
        self.assertFalse(h.has_emission)
        self.assertAlmostEqual(h.max_density, 0.4590, places=3)
        self.assertEqual(h.extent, (119.0, 114.0, 103.0))

    def test_reads_bunny_cloud_which_has_seven_mips(self):
        h = vp.read_baked_header(DATA / "bunny_cloud.bin")
        self.assertEqual(h.num_mips, 7)
        self.assertFalse(h.has_velocity)
        self.assertAlmostEqual(h.max_density, 2.7923, places=3)
        self.assertEqual(h.extent, (577.0, 572.0, 438.0))

    def test_rejects_a_file_that_is_not_a_bake(self):
        with self.assertRaises(ValueError):
            vp.read_baked_header(SCRIPTS / "datasets.json")


class TestIsBinComplete(unittest.TestCase):
    def test_true_for_a_real_bake(self):
        self.assertTrue(vp.is_bin_complete(DATA / "bunny_cloud.bin"))

    def test_false_for_missing_file(self):
        self.assertFalse(vp.is_bin_complete(DATA / "does_not_exist.bin"))

    def test_false_for_truncated_file(self):
        import tempfile, os
        src = (DATA / "bunny_cloud.bin").read_bytes()[:5000]
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(src)
            name = f.name
        try:
            self.assertFalse(vp.is_bin_complete(name))
        finally:
            os.unlink(name)


if __name__ == "__main__":
    unittest.main()
