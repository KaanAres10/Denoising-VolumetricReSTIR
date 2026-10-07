import json
import os
import tempfile
import unittest

import cost_table


class TestEqualTimeCandidates(unittest.TestCase):
    def test_interpolates_between_measured_counts(self):
        self.assertAlmostEqual(cost_table.equal_time_candidates({4: 10.0, 8: 20.0, 16: 40.0}, 30.0), 12.0)

    def test_exact_measured_count(self):
        self.assertAlmostEqual(cost_table.equal_time_candidates({4: 10.0, 8: 20.0}, 20.0), 8.0)

    def test_above_the_measured_range_extrapolates_the_last_segment(self):
        # Cost is linear in the candidate count: 2.5 ms per candidate between 4 and 8.
        self.assertAlmostEqual(cost_table.equal_time_candidates({4: 10.0, 8: 20.0}, 25.0), 10.0)

    def test_below_the_cheapest_count(self):
        self.assertIsNone(cost_table.equal_time_candidates({4: 10.0, 8: 20.0}, 5.0))


class TestRow(unittest.TestCase):
    def write(self, root, label, cfg, total, mutate=None):
        d = os.path.join(root, "cost", label, cfg)
        os.makedirs(d)
        lanes = {cost_table.PREFIX + "/gpu_time": {"median": total}}
        if mutate is not None:
            lanes[cost_table.PREFIX + "/Mutate Samples/gpu_time"] = {"median": mutate}
        with open(os.path.join(d, "c.passes.json"), "w") as fh:
            json.dump(lanes, fh)

    def test_row_reads_totals_pass_and_equal_time(self):
        with tempfile.TemporaryDirectory() as root:
            self.write(root, "s", "mut0", 10.0)
            self.write(root, "s", "mut1", 12.0, 2.0)
            self.write(root, "s", "mut5", 18.0, 8.0)
            self.write(root, "s", "im8", 14.0)
            self.write(root, "s", "im16", 22.0)
            r = cost_table.row(root, "s")
        self.assertEqual((r["plain"], r["mut1"], r["mut5"], r["pass1"], r["pass5"]), (10.0, 12.0, 18.0, 2.0, 8.0))
        self.assertAlmostEqual(r["equal_time_candidates_1"], 6.0)
        self.assertAlmostEqual(r["equal_time_candidates_5"], 12.0)

    def test_missing_runs_give_no_row(self):
        with tempfile.TemporaryDirectory() as root:
            self.write(root, "s", "mut0", 10.0)
            self.assertIsNone(cost_table.row(root, "s"))


if __name__ == "__main__":
    unittest.main()
