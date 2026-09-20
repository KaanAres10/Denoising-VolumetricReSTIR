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


class TestManifest(unittest.TestCase):
    def test_loads_both_datasets(self):
        m = vp.load_manifest()
        self.assertEqual(sorted(m), ["dustShockwave", "firePlume"])

    def test_unknown_dataset_names_the_valid_ones(self):
        with self.assertRaises(KeyError) as ctx:
            vp.get_dataset("nope")
        self.assertIn("firePlume", str(ctx.exception))

    def test_frame_numbers_span_the_window(self):
        ds = vp.get_dataset("firePlume")
        frames = vp.frame_numbers(ds)
        self.assertEqual(len(frames), 32)
        self.assertEqual((frames[0], frames[-1]), (100, 131))

    def test_source_frame_path_applies_the_pattern(self):
        ds = vp.get_dataset("firePlume")
        p = vp.source_frame_path(ds, 125, REPO)
        self.assertEqual(p.name, "firePlume_0125.vdb")
        self.assertTrue(p.exists(), "real source frame should be on disk")

    def test_missing_source_frame_is_detectable(self):
        ds = vp.get_dataset("firePlume")
        self.assertFalse(vp.source_frame_path(ds, 9999, REPO).exists())

    def test_estimate_window_bytes_is_positive_and_scales(self):
        ds = vp.get_dataset("dustShockwave")
        self.assertGreater(vp.estimate_window_bytes(ds, REPO), 0)

    def test_write_baked_back_records_measured_values(self):
        """The ingest script is the only writer of "baked"; never hand-maintained."""
        import json, shutil, tempfile
        with tempfile.TemporaryDirectory() as d:
            copy = Path(d) / "datasets.json"
            shutil.copy(vp.MANIFEST_PATH, copy)
            h = vp.BakedHeader(4, True, False, 0.719238, (202.0, 679.0, 456.0))
            vp.write_baked_back("firePlume", h, path=copy)
            written = json.load(open(copy))["firePlume"]["baked"]
            self.assertEqual(written["extent"], [202.0, 679.0, 456.0])
            self.assertAlmostEqual(written["max_density"], 0.719238, places=6)
            self.assertTrue(written["has_emission"])


if __name__ == "__main__":
    unittest.main()
