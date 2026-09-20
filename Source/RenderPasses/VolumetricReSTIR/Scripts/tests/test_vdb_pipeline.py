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


class TestPlacement(unittest.TestCase):
    def test_translation_is_the_centre_not_the_min_corner(self):
        """Pinned to observed runtime output, not to a derivation.

        Passing translation (0.0153, 1.68, 0.538) for an 801x796x140 volume at scale 0.0018844
        made Falcor log worldBB min(-0.735, 0.958, 0.360) -- translation minus HALF the scaled
        extent. So worldTranslation is the centre and must pass through untouched.
        """
        extent = (801.0, 796.0, 140.0)
        centre = (0.0, 1.686, 0.0)
        scale, trans = vp.derive_placement(extent, centre, 1.5)
        self.assertEqual(trans, centre)
        observed_min = tuple(trans[i] - extent[i] * scale * 0.5 for i in range(3))
        self.assertAlmostEqual(observed_min[0], -0.7547, places=3)

    def test_scale_reproduces_the_fire115_world_scaling(self):
        """fire115 is 114 voxels tall and was hand-tuned to worldScaling 0.013."""
        scale, _ = vp.derive_placement((119.0, 114.0, 103.0), (0, 0, 0), 114.0 * 0.013)
        self.assertAlmostEqual(scale, 0.013, places=6)

    def test_scale_sets_the_target_height(self):
        scale, _ = vp.derive_placement((202.0, 679.0, 456.0), (0, 0, 0), 1.5)
        self.assertAlmostEqual(679.0 * scale, 1.5, places=6)

    def test_density_scale_preserves_reference_thickness(self):
        """densityScale/worldScaling is what the shader uses, so the ratio must be held."""
        self.assertAlmostEqual(vp.derive_density_scale(0.1, 0.013), 0.1, places=6)
        self.assertAlmostEqual(vp.derive_density_scale(0.1, 1.5 / 679.0), 0.017, places=3)

    def test_middle_frame_is_used_for_placement(self):
        """V1 found GVDB rebases every frame's origin, so a growing volume anchored on frame 0
        drifts. Centring on the middle frame halves that error."""
        self.assertEqual(vp.placement_frame([60, 61, 62, 63]), 62)
        self.assertEqual(vp.placement_frame([100]), 100)


class TestPlaybackFrames(unittest.TestCase):
    """addGVDBVolumeSequence uploads every frame up front, so a window that ingests fine can
    still exceed VRAM at playback. Measured on an 8 GB RTX 5070: dustShockwave at 677 MB/frame
    plays 16 frames and dies with DXGI_ERROR_DEVICE_REMOVED at 24."""

    def test_playback_cap_limits_the_window(self):
        ds = dict(vp.get_dataset("dustShockwave"), playback_frames=16)
        frames = vp.playback_frame_numbers(ds)
        self.assertEqual(len(frames), 16)
        self.assertEqual(frames[0], ds["start_frame"])

    def test_without_a_cap_playback_uses_the_whole_window(self):
        ds = vp.get_dataset("firePlume")
        self.assertEqual(len(vp.playback_frame_numbers(ds)), len(vp.frame_numbers(ds)))

    def test_ingest_is_unaffected_by_the_playback_cap(self):
        """The cap is a GPU limit, not an ingest limit: all 32 frames still get baked."""
        ds = dict(vp.get_dataset("dustShockwave"), playback_frames=16)
        self.assertEqual(len(vp.frame_numbers(ds)), 32)


class TestEncodeVideo(unittest.TestCase):
    def setUp(self):
        import encode_video
        self.ev = encode_video

    def test_orders_frames_by_trailing_index_not_lexically(self):
        """Mogwai writes <base>.<pass>.<output>.<frame>.png with STRIDED frame numbers, so a
        printf pattern cannot address them and a lexical sort puts .128. before .32."""
        names = ["frame.ToneMapper.dst.128.png", "frame.ToneMapper.dst.32.png",
                 "frame.ToneMapper.dst.64.png"]
        self.assertEqual([Path(p).name for p in self.ev.sort_frames(names)],
                         ["frame.ToneMapper.dst.32.png", "frame.ToneMapper.dst.64.png",
                          "frame.ToneMapper.dst.128.png"])

    def test_missing_ffmpeg_raises_rather_than_silently_doing_nothing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            Path(d, "frame.ToneMapper.dst.1.png").write_bytes(b"x")
            with self.assertRaises(RuntimeError):
                self.ev.encode(d, Path(d) / "out.mp4", 24, ffmpeg="definitely_not_ffmpeg")

    def test_no_frames_raises(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                self.ev.encode(d, Path(d) / "out.mp4", 24)


if __name__ == "__main__":
    unittest.main()
