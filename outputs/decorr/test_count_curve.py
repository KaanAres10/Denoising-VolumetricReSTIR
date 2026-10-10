import json
import os
import tempfile
import unittest

import count_curve


def write(root, label, cfg, medium, rb, gm, dup=1.0):
    d = os.path.join(root, label, cfg)
    os.makedirs(d)
    with open(os.path.join(d, "c.corr.json"), "w") as fh:
        json.dump({"medium": {"rho": {"8": medium}}, "color_rb": {"rho": {"8": rb}}, "color_gm": {"rho": {"8": gm}},
                   "duplicates": {"sample_mean": dup}}, fh)


class TestCountCurve(unittest.TestCase):
    def test_reads_only_the_prefix_and_parses_the_count(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "s", "c200_m0", 0.1, 0.02, 0.04)
            write(root, "s", "c200_m10", 0.05, 0.01, 0.01)
            write(root, "s", "ship_m1", 0.9, 0.9, 0.9)
            write(root, "s", "noreuse", 0.9, 0.9, 0.9)
            series = count_curve.load_counts(root, "s", "c200")
        self.assertEqual(sorted(series), [0, 10])
        self.assertAlmostEqual(series[0]["medium"], 0.1)
        self.assertAlmostEqual(series[0]["colour"], 0.03)  # the mean of the two colour-difference channels
        self.assertAlmostEqual(series[10]["dup"], 1.0)

    def test_one_mutation_leaves_most_of_the_cut(self):
        share, cut = count_curve.cut_share({0: 0.10, 1: 0.08, 5: 0.04, 20: 0.02})
        self.assertAlmostEqual(share, 0.25)  # one mutation removes a quarter of what twenty remove
        self.assertAlmostEqual(cut, 0.8)     # twenty remove 80% of the correlation
        self.assertTrue(count_curve.needs_more(share, cut))

    def test_one_mutation_is_enough(self):
        share, cut = count_curve.cut_share({0: 0.10, 1: 0.03, 20: 0.02})
        self.assertAlmostEqual(share, 0.875)
        self.assertFalse(count_curve.needs_more(share, cut))

    def test_no_real_cut_never_qualifies(self):
        share, cut = count_curve.cut_share({0: 0.10, 1: 0.10, 20: 0.095})
        self.assertAlmostEqual(cut, 0.05)
        self.assertFalse(count_curve.needs_more(share, cut))

    def test_missing_counts_give_none(self):
        self.assertEqual(count_curve.cut_share({0: 0.1, 20: 0.02}), (None, None))
        self.assertEqual(count_curve.cut_share({1: 0.1, 20: 0.02}), (None, None))
        self.assertFalse(count_curve.needs_more(None, None))


if __name__ == "__main__":
    unittest.main()
