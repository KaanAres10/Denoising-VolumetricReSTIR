"""correlation_schedule.build_schedule: when correlation_pose.py seeds chains and captures frames.

    python -m unittest test_correlation_schedule -v
"""
import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from correlation_schedule import build_schedule


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


if __name__ == "__main__":
    unittest.main()
