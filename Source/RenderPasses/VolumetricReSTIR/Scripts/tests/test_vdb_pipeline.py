import sys, tempfile, unittest
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

    def test_false_when_the_header_is_intact_but_the_payload_is_cut(self):
        """The disk-full case. GVDBBake never checks its fwrite returns and exits 0 regardless,
        so a bake that fills the disk leaves a file whose 11 KB header is perfectly valid and
        whose 600 MB payload is missing. Validating only the header would rename that into place
        and every later resume would skip it as finished."""
        import tempfile, os
        with open(DATA / "bunny_cloud.bin", "rb") as f:
            src = f.read(4 * 1024 * 1024)      # valid header, payload truncated
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(src)
            name = f.name
        try:
            vp.read_baked_header(name)         # header alone still parses - that is the trap
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

    def test_estimate_window_bytes_scales_with_the_frame_count(self):
        """firePlume is flat at ~41 MB/frame, so doubling the window doubles the estimate.
        dustShockwave grows monotonically, so its longer window also samples bigger frames and
        the ratio exceeds 2 -- checked here so that behaviour stays deliberate."""
        fire = vp.get_dataset("firePlume")
        half = vp.estimate_window_bytes(dict(fire, num_frames=16), REPO)
        full = vp.estimate_window_bytes(dict(fire, num_frames=32), REPO)
        self.assertGreater(half, 0)
        self.assertAlmostEqual(full / half, 2.0, places=1)

        dust = vp.get_dataset("dustShockwave")
        d_half = vp.estimate_window_bytes(dict(dust, num_frames=16), REPO)
        d_full = vp.estimate_window_bytes(dict(dust, num_frames=32), REPO)
        self.assertGreater(d_full / d_half, 2.0)

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
    def test_translation_passes_through_as_the_volume_centre(self):
        """worldTranslation is the volume's CENTRE, so derive_placement must not adjust it.

        Measured, not derived: passing translation (0.0153, 1.68, 0.538) for an 801x796x140
        volume at scale 0.0018844 made Falcor log worldBB min(-0.735, 0.958, 0.360) -- the
        translation minus HALF the scaled extent. An earlier version subtracted half the extent
        here as well, which would have double-counted and put every volume off camera.
        """
        centre = (0.0, 1.686, 0.0)
        _, trans = vp.derive_placement((801.0, 796.0, 140.0), centre, 1.5)
        self.assertEqual(trans, centre)

    def test_scale_reproduces_the_fire115_world_scaling(self):
        """fire115 is 114 voxels tall and 1.482 world units tall at its hand-tuned 0.013."""
        scale, _ = vp.derive_placement((119.0, 114.0, 103.0), (0, 0, 0), 1.482)
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


class TestIngestFailurePaths(unittest.TestCase):
    """The three failure modes the plan named as most likely to bite. Each is exercised with a
    fake runner so no executable, GPU or multi-GB source is needed."""

    def setUp(self):
        import ingest_vdb_sequence as ing
        self.ing = ing
        self._saved = (ing.GIMPORT_DIR, ing.BAKE_DIR, ing.VDBPREP_DIR)
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        ing.GIMPORT_DIR = ing.BAKE_DIR = ing.VDBPREP_DIR = tmp
        self.out = tmp / "out"
        self.out.mkdir()

    def tearDown(self):
        self.ing.GIMPORT_DIR, self.ing.BAKE_DIR, self.ing.VDBPREP_DIR = self._saved
        self._tmp.cleanup()

    def _ds(self, **over):
        ds = dict(vp.get_dataset("dustShockwave"))
        ds.update(over)
        return ds

    def test_missing_source_frame_fails_loudly_naming_it(self):
        with self.assertRaises(SystemExit) as ctx:
            self.ing.ingest_frame(self._ds(), 9999, self.out, False, False,
                                  runner=lambda *a, **k: None)
        self.assertIn("9999", str(ctx.exception))

    def test_emission_without_a_temperature_grid_fails(self):
        """Otherwise the volume renders black, indistinguishable from bad emission tuning."""
        def fake(cmd, cwd):
            # stand in for gImportVDB: produce the vbx folder but no _temperature.vbx
            (self.ing.GIMPORT_DIR / "dustshockwave_0060").mkdir(exist_ok=True)
        with self.assertRaises(SystemExit) as ctx:
            self.ing.ingest_frame(self._ds(has_emission=True, grid_renames={}), 60,
                                  self.out, False, False, runner=fake)
        self.assertIn("temperature", str(ctx.exception))

    def test_an_incomplete_bake_is_rejected_and_leaves_no_bin(self):
        """The disk-full case: GVDBBake exits 0 having written a partial file."""
        def fake(cmd, cwd):
            name = str(cmd[0])
            if "gImportVDB" in name:
                (self.ing.GIMPORT_DIR / "dustshockwave_0060").mkdir(exist_ok=True)
            else:
                Path(cmd[-1]).write_bytes(b"\x47\x56\x44\x42" + b"\0" * 32)  # valid magic, no body
        with self.assertRaises(SystemExit) as ctx:
            self.ing.ingest_frame(self._ds(), 60, self.out, False, False, runner=fake)
        self.assertIn("not a valid bake", str(ctx.exception))
        self.assertEqual(list(self.out.glob("*.bin")), [],
                         "a rejected bake must not be renamed into place")

    def test_preflight_names_a_missing_executable(self):
        with self.assertRaises(SystemExit) as ctx:
            self.ing.preflight(self._ds(), REPO)
        self.assertIn(".exe", str(ctx.exception))


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

    def test_encodes_exactly_one_video_frame_per_capture(self):
        """Real ffmpeg round trip. Per-file `duration` directives plus CFR conversion emitted an
        extra trailing frame -- 33 encoded for 32 captured -- which shows as a hitch at the loop
        point."""
        import shutil as _sh
        import subprocess
        if _sh.which("ffmpeg") is None or _sh.which("ffprobe") is None:
            self.skipTest("ffmpeg/ffprobe not on PATH")
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for i in range(1, 6):
                Image.new("RGB", (64, 48), (i * 40 % 256, 20, 30)).save(d / f"frame.Tone.dst.{i}.png")
            out = d / "out.mp4"
            self.ev.encode(d, out, fps=24)
            n = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=nb_frames", "-of", "csv=p=0", str(out)],
                               capture_output=True, text=True).stdout.strip()
            self.assertEqual(int(n), 5)

    def test_no_frames_raises(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                self.ev.encode(d, Path(d) / "out.mp4", 24)


if __name__ == "__main__":
    unittest.main()
