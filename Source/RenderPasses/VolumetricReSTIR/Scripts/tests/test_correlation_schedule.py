"""correlation_schedule.build_schedule: when correlation_pose.py seeds chains and captures frames.

    python -m unittest test_correlation_schedule -v
"""
import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from correlation_schedule import band_rows, build_schedule, parse_rows, strip_frames


def seed_ranges(s):
    ranges = [(c["seed"], c["seed"] + c["length"]) for c in s["chains"]]
    if s["burst"]:
        ranges.append((s["burst"]["seed"], s["burst"]["seed"] + s["burst"]["length"]))
    return ranges


class TestSchedule(unittest.TestCase):
    def test_first_capture_follows_the_warm_up(self):
        s = build_schedule(f0=10, chains=3, per_chain=4, warm=256, spacing=33)
        self.assertEqual(s["chains"][0]["first"], 11)
        self.assertEqual(s["chains"][0]["frames"][0], 10 + 256 + 1)

    def test_captures_within_a_chain_are_spaced(self):
        s = build_schedule(f0=0, chains=2, per_chain=5, warm=64, spacing=17)
        for chain in s["chains"]:
            self.assertEqual(len(chain["frames"]), 5)
            self.assertEqual({b - a for a, b in zip(chain["frames"], chain["frames"][1:])}, {17})
            self.assertEqual(chain["frames"][-1], chain["first"] + chain["length"] - 1)

    def test_chains_run_back_to_back(self):
        s = build_schedule(f0=5, chains=3, per_chain=2, warm=10, spacing=3)
        for a, b in zip(s["chains"], s["chains"][1:]):
            self.assertEqual(b["first"], a["first"] + a["length"])
        self.assertEqual(s["total"], 3 * (10 + 3 + 1))

    def test_seed_ranges_never_overlap(self):
        # Every random stream is seeded from the frame count: overlapping ranges would replay the same
        # random numbers and make two "independent" chains converge to the same images.
        s = build_schedule(f0=0, chains=20, per_chain=10, warm=800, spacing=129, burst=256)
        for (a0, a1), (b0, b1) in itertools.combinations(seed_ranges(s), 2):
            self.assertTrue(a1 <= b0 or b1 <= a0, ((a0, a1), (b0, b1)))

    def test_too_small_a_stride_is_refused(self):
        with self.assertRaises(ValueError):
            build_schedule(f0=0, chains=2, per_chain=10, warm=256, spacing=33, seed_stride=300)

    def test_seeds_stay_clear_of_int32_overflow(self):
        # Shaders seed with numTotalRounds * frameCount + round in 32-bit ints (numTotalRounds <= ~8).
        with self.assertRaises(ValueError):
            build_schedule(f0=0, chains=10, per_chain=10, warm=256, spacing=33, seed_base=300_000_000)

    def test_burst_captures_consecutive_frames_after_its_warm_up(self):
        s = build_schedule(f0=0, chains=2, per_chain=3, warm=50, spacing=7, burst=40)
        b = s["burst"]
        self.assertEqual(b["first"], s["chains"][-1]["first"] + s["chains"][-1]["length"])
        self.assertEqual(b["frames"], list(range(b["first"] + 50, b["first"] + 50 + 40)))
        self.assertEqual(s["total"], 2 * (50 + 2 * 7 + 1) + 50 + 40)

    def test_no_burst_by_default(self):
        self.assertIsNone(build_schedule(f0=0, chains=1, per_chain=1, warm=1, spacing=1)["burst"])


class TestStrip(unittest.TestCase):
    """The space-time strips (VR_STRIP_ROWS, VR_STRIP_FRAMES): a band of rows kept from consecutive frames."""

    def test_rows_are_a_band_inside_the_frame(self):
        self.assertEqual(parse_rows("100:132", 540), (100, 132))
        for bad in ("530:560", "200:200", "40:20", "-1:10", "x:y", "100"):
            with self.assertRaises(ValueError, msg=bad):
                parse_rows(bad, 540)

    def test_strip_starts_at_the_last_chains_capture_and_runs_on(self):
        s = build_schedule(f0=0, chains=2, per_chain=1, warm=800, spacing=5)  # the paper's five-denoiser runs
        self.assertEqual(strip_frames(s, 4), [1602, 1603, 1604, 1605])  # its first row is the paper's frame 1602
        self.assertEqual(strip_frames(s, 1), [1602])

    def test_a_strip_needs_frames_and_no_burst(self):
        s = build_schedule(f0=0, chains=1, per_chain=1, warm=10, spacing=1)
        with self.assertRaises(ValueError):
            strip_frames(s, 0)
        with self.assertRaises(ValueError):  # the burst would run after the chain the strip continues
            strip_frames(build_schedule(f0=0, chains=1, per_chain=1, warm=10, spacing=1, burst=8), 4)

    def test_kept_rows_do_not_hold_on_to_the_frame(self):
        import numpy as np
        frame = np.arange(1080 * 1920 * 4, dtype=np.float32).reshape(1080, 1920, 4)  # a texture's to_numpy(), RGBA
        rows = band_rows(frame, 208, 240)
        self.assertEqual(rows.shape, (32, 1920, 3))
        self.assertEqual(rows.dtype, np.float32)
        self.assertIsNone(rows.base)  # its own 0.7 MB: a view would keep the 33 MB frame for every frame kept
        np.testing.assert_array_equal(rows, frame[208:240, :, :3])


if __name__ == "__main__":
    unittest.main()
