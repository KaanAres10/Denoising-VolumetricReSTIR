"""five_figures.py: the teaser's setup and the chart, on synthetic results.

    cd outputs/decorr && python -m unittest test_five_figures -v
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import five_figures as ff


def results(cuts):
    """{label: cut per denoiser at M cap 200}, plain relMSE 0.1 everywhere, the shipped cap halving the cut."""
    out = {}
    for label, c in cuts.items():
        h = {}
        for hist, k in (("c200", 1.0), ("ship", 0.5)):
            h[hist] = {"m0": {d: {"mean": 0.1} for d in ff.DENOISERS},
                       "m5": {d: {"mean": 0.1 * (1 - k * c[i])} for i, d in enumerate(ff.DENOISERS)}}
        out[label] = {"histories": h, "ref_own_relmse": 0.001}
    return out


class TestTeaser(unittest.TestCase):
    def test_the_largest_median_cut(self):
        r = results({"a": [0.9, 0.1, 0.1, 0.1, 0.9], "b": [0.5, 0.5, 0.5, 0.5, 0.5], "c": [0.6, 0.6, 0.2, 0.2, 0.6]})
        self.assertAlmostEqual(ff.cut(r, "b", "c200", "oidn"), 0.5)
        self.assertEqual(ff.teaser_setup(r), "c")  # medians: a 0.1, b 0.5, c 0.6

    def test_a_setup_missing_a_denoiser_is_not_chosen(self):
        r = results({"a": [0.9] * 5, "b": [0.5] * 5})
        del r["a"]["histories"]["c200"]["m5"]["rr"]
        self.assertEqual(ff.teaser_setup(r), "b")


class TestChart(unittest.TestCase):
    def test_writes_the_chart(self):
        r = results({"a": [0.8] * 5, "b": [0.4] * 5})
        with tempfile.TemporaryDirectory() as root:
            out = os.path.join(root, "history_chart.pdf")
            ff.history_chart(r, out)
            self.assertGreater(os.path.getsize(out), 1000)


if __name__ == "__main__":
    unittest.main()
