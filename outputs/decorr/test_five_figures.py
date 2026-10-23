"""five_figures.py: the teaser's setup, the error maps, the page and block layouts and the chart, on synthetic results
and frames.

    cd outputs/decorr && python -m unittest test_five_figures -v
"""
import os
import sys
import tempfile
import types
import unittest

import numpy as np

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


def frames(size=60, seed=0):
    """A setup's frames without the disk: noisy copies of a smooth reference, the medium inside a margin, the box in
    the medium."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size] / size
    ref = np.stack([0.2 + 0.6 * xx, 0.2 + 0.6 * yy, np.full_like(xx, 0.5)], -1)
    imgs = {d: (ref + rng.normal(0, 0.05, ref.shape), ref + rng.normal(0, 0.01, ref.shape)) for d in ff.DENOISERS}
    mask = np.zeros((size, size), bool)
    mask[5:-5, 5:-5] = True
    return types.SimpleNamespace(imgs=imgs, ref=ref, mask=mask, box=(10, 10, 30), show=lambda a: np.clip(a, 0, 1))


def height_width(path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.image
    return matplotlib.image.imread(path).shape[:2]


class TestErrorMap(unittest.TestCase):
    def test_signed_luminance_error_inside_the_medium(self):
        ref = np.full((40, 40, 3), 0.5)
        mask = np.zeros((40, 40), bool)
        mask[10:30, 10:30] = True
        brighter = ff.signed_error(ref + 0.1, ref, mask)
        self.assertAlmostEqual(float(brighter[20, 20]), 0.1, places=4)  # Y_RGB sums to 1
        self.assertLess(float(ff.signed_error(ref - 0.1, ref, mask)[20, 20]), 0.0)
        self.assertTrue(np.isnan(brighter[0, 0]))  # outside the medium: drawn grey, not as no error

    def test_pin_holes_in_the_medium_are_not_drawn_as_outside_it(self):
        ref = np.full((40, 40, 3), 0.5)
        mask = np.zeros((40, 40), bool)
        mask[5:35, 5:35] = True
        mask[10:30:4, 10:30:4] = False  # the night street's fog: single pixels missing from the medium
        e = ff.signed_error(ref + 0.1, ref, mask)
        self.assertFalse(np.isnan(e[14, 14]))  # a hole: filled from its neighbours in the medium
        self.assertAlmostEqual(float(e[14, 14]), 0.1, places=4)  # the blur stays inside the medium
        self.assertTrue(np.isnan(e[1, 1]))

    def test_one_scale_per_setup_that_one_denoiser_cannot_set(self):
        maps = [np.full((8, 8), v) for v in (1.0, -2.0, 3.0, 4.0, 100.0)]
        maps[0][0, 0] = np.nan
        self.assertAlmostEqual(ff.error_limit(maps), 3.0)  # the median of the plain maps' 99th percentiles


class TestImport(unittest.TestCase):
    def test_frames_still_read_after_importing_five_figures(self):
        import cv2  # five_figures imported it first, so it must have enabled OpenEXR before that
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "f.exr")
            cv2.imwrite(path, np.ones((4, 4, 3), np.float32))
            self.assertEqual(cv2.imread(path, cv2.IMREAD_UNCHANGED).shape, (4, 4, 3))


class TestLayouts(unittest.TestCase):
    def test_one_setup_fills_a_page_at_the_text_width(self):
        r = results({"a": [0.5] * 5})
        with tempfile.TemporaryDirectory() as root:
            out = os.path.join(root, "page.png")
            ff.page_figure(frames(), ff.block_titles(r, "a"), out)
            h, w = height_width(out)
        self.assertEqual(w, 2100)  # 7 in at 300 dpi: placed at scale 1, so its fonts keep their sizes
        self.assertTrue(w < h < 1.165 * w)  # fits the 8.66 in text block with a two-line caption

    def test_the_page_puts_a_large_whole_frame_over_six_columns(self):
        lay = ff.page_layout((1080, 1920))
        self.assertGreaterEqual(lay["frame"][2], 4.5)  # the whole frame's width in inches (was 3.2)
        self.assertEqual(lay["columns"], list(ff.DENOISERS) + ["reference"])  # beside the plain and mutated crops
        self.assertGreaterEqual(lay["crop"], 1.0)
        self.assertLess(lay["height"], 1.165 * ff.WIDTH)  # still one page with its caption

    def test_the_teaser_is_a_wide_band_at_the_same_width(self):
        r = results({"a": [0.5] * 5})
        with tempfile.TemporaryDirectory() as root:
            out = os.path.join(root, "teaser.png")
            ff.teaser_figure(frames(), ff.block_titles(r, "a"), out)
            h, w = height_width(out)
        self.assertEqual(w, 2100)
        self.assertLess(h, 0.75 * w)  # leaves the first page room for the abstract


class TestBlock(unittest.TestCase):
    def test_plain_above_mutated_below_with_the_reference_last(self):
        r = results({"a": [0.5, 0.5, 0.5, 0.5, 0.5]})
        t = ff.block_titles(r, "a", "c200")
        self.assertEqual([len(row) for row in t], [6, 6])
        self.assertEqual(t[0][0], "0.1000")
        self.assertEqual(t[1][0], "0.0500 (−50%)")
        self.assertEqual(t[0][5], "")  # the reference column is named in the header only


class TestChart(unittest.TestCase):
    def test_writes_the_chart(self):
        r = results({"a": [0.8] * 5, "b": [0.4] * 5})
        with tempfile.TemporaryDirectory() as root:
            out = os.path.join(root, "history_chart.pdf")
            ff.history_chart(r, out)
            self.assertGreater(os.path.getsize(out), 1000)


if __name__ == "__main__":
    unittest.main()
