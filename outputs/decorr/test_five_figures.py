"""five_figures.py: the teaser's setup, the error maps, the page, cover and block layouts and the chart, on synthetic
results and frames.

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


def overlaps(fig):
    """Every word on `fig` that overlaps a picture (a crop, an error map, a frame) or another word, as messages."""
    import matplotlib.pyplot as plt
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    pictures = [ax.get_window_extent(rend) for ax in fig.axes if ax.images]
    words = [t for t in fig.texts if t.get_text()]
    for ax in fig.axes:
        words += [t for t in (ax.title, ax.xaxis.label, ax.yaxis.label) if t.get_text()]
        words += [t for t in ax.get_yticklabels() if t.get_text()]
    boxes = [(t.get_text(), t.get_window_extent(rend)) for t in words]
    plt.close(fig)
    found = ["%r overlaps a picture" % text for text, box in boxes if any(box.overlaps(pic) for pic in pictures)]
    for i, (a, box_a) in enumerate(boxes):  # nor each other (the scale's words and its tick labels)
        found += ["%r overlaps %r" % (a, b) for b, box_b in boxes[i + 1:] if box_a.overlaps(box_b)]
    return found


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

    def test_no_words_overlap_the_pictures(self):
        r = results({"a": [0.5] * 5})
        self.assertEqual(overlaps(ff.page_canvas(frames(), ff.block_titles(r, "a"))), [])

    def test_the_teaser_is_a_wide_band_at_the_same_width(self):
        r = results({"a": [0.5] * 5})
        with tempfile.TemporaryDirectory() as root:
            out = os.path.join(root, "teaser.png")
            ff.teaser_figure(frames(), ff.block_titles(r, "a"), out)
            h, w = height_width(out)
        self.assertEqual(w, 2100)
        self.assertLess(h, 0.75 * w)  # leaves the first page room for the abstract


class TestCover(unittest.TestCase):
    """The cover (the paper's first figure and the project page's): plain ReSTIR, + 5 mutations and the reference
    through one denoiser, the whole medium on top and a zoom below."""

    def test_the_view_is_a_square_around_the_whole_medium_inside_the_frame(self):
        mask = np.zeros((54, 96), bool)
        mask[3:50, 30:70] = True  # taller than wide, in a wide frame
        y, x, side = ff.cover_view(mask, pad=2)
        self.assertEqual(side, 51)  # the medium's height, 47, and the pad on both sides
        self.assertTrue(0 <= y and y + side <= 54 and 0 <= x and x + side <= 96)
        self.assertTrue(y <= 3 and y + side >= 50 and x <= 30 and x + side >= 70)

    def test_a_medium_as_tall_as_the_frame_gets_the_frame_height(self):
        mask = np.zeros((54, 96), bool)
        mask[:, 40:60] = True
        y, x, side = ff.cover_view(mask, pad=12)
        self.assertEqual((y, side), (0, 54))
        self.assertTrue(x <= 40 and x + side >= 60)

    def test_the_heads_name_the_denoiser_and_carry_the_relmse(self):
        r = results({"a": [0.5] * 5})
        self.assertEqual(ff.cover_titles(r, "a", "rr"),
                         [("Plain ReSTIR", "DLSS RR · relMSE 0.1000"),
                          ("+ 5 mutations", "DLSS RR · relMSE 0.0500 (−50%)"), ("Reference", "path traced")])
        self.assertEqual(ff.cover_titles(r, "a", "optix", sep="\n")[1][1], "OptiX\nrelMSE 0.0500 (−50%)")

    def test_the_cover_is_the_text_width_and_leaves_room_for_the_abstract(self):
        r = results({"a": [0.5] * 5})
        with tempfile.TemporaryDirectory() as root:
            out = os.path.join(root, "cover.png")
            ff.cover_figure(frames(), ff.cover_titles(r, "a", "rr"), "rr", (12, 14, 20), out)
            h, w = height_width(out)
        self.assertEqual(w, 2100)  # 7 in at 300 dpi, like the other figures
        self.assertLess(h, 0.75 * w)  # the teaser's bound: the first page keeps room for the abstract
        self.assertGreater(h, 0.7 * w)  # two rows of three squares: the whole medium and the zoom

    def test_no_words_overlap_the_cover_pictures(self):
        r = results({"a": [0.5] * 5})
        fig = ff.cover_canvas(frames(), ff.cover_titles(r, "a", "rr"), "rr", (12, 14, 20))
        self.assertEqual(len([ax for ax in fig.axes if ax.images]), 6)
        self.assertEqual(overlaps(fig), [])

    def test_the_phone_cover_keeps_plain_and_mutated_in_two_narrow_columns(self):
        r = results({"a": [0.5] * 5})
        fig = ff.cover_canvas(frames(), ff.cover_titles(r, "a", "rr", sep="\n"), "rr", (12, 14, 20), columns=2,
                              width=3.4)
        self.assertEqual(len([ax for ax in fig.axes if ax.images]), 4)  # the reference's column dropped
        self.assertAlmostEqual(fig.get_size_inches()[0], 3.4)
        self.assertEqual(overlaps(fig), [])  # the two-line heads fit their columns

    def test_the_heads_are_set_in_the_project_pages_font(self):
        if not all(os.path.exists(f) for f in ff.COVER_FONTS):
            self.skipTest("Segoe UI is not installed")
        import matplotlib.pyplot as plt
        r = results({"a": [0.5] * 5})
        fig = ff.cover_canvas(frames(), ff.cover_titles(r, "a", "rr"), "rr", (12, 14, 20))
        files = [t.get_fontproperties().get_file() for t in fig.texts]
        plt.close(fig)
        self.assertEqual(files[:2], list(ff.COVER_FONTS))  # a column's name semibold, its second line regular
        self.assertEqual(set(files), set(ff.COVER_FONTS))

    def test_a_zoom_outside_the_whole_view_is_refused(self):
        p = frames()
        p.mask[:] = False
        p.mask[30:50, 30:50] = True  # the view: a 44 px square from (16, 16)
        r = results({"a": [0.5] * 5})
        with self.assertRaises(ValueError):
            ff.cover_canvas(p, ff.cover_titles(r, "a", "rr"), "rr", (0, 0, 10))


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
