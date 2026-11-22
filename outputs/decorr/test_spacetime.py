"""spacetime.py: the space-time strips' error field, its statistics and where each channel's strip is, on synthetic
fields with known answers.

    cd outputs/decorr && python -m unittest test_spacetime -v
"""
import os
import sys
import tempfile
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import medium_metrics as mm
import spacetime as st


def band(t=64, r=8, w=96, seed=0):
    rng = np.random.default_rng(seed)
    ref = np.stack([np.linspace(0.2, 1.0, w)] * r)[..., None] * np.ones(3)
    mask = np.ones((r, w), bool)
    mask[:, :8] = False  # outside the medium
    return rng, ref, mask


class TestErrorField(unittest.TestCase):
    def test_its_mean_square_over_the_medium_is_the_papers_relmse(self):
        rng, ref, mask = band(t=1)
        img = ref * (1 + 0.2 * rng.standard_normal(ref.shape))
        e = st.error_field(img[None], ref, mask)
        self.assertEqual(e.shape, (1,) + mask.shape)
        self.assertTrue(np.isnan(e[0][~mask]).all())  # outside the medium: no error
        self.assertAlmostEqual(float(np.nanmean(e ** 2)), mm.relmse(img, ref, mask), places=10)


class TestStats(unittest.TestCase):
    """stats(e, c0): e a strip's error field over its frames, c0 an independent chain's at the same pixels."""

    def field(self, values, mask):
        e = np.array(values, dtype=np.float64)
        e[..., ~mask] = np.nan
        return e

    def test_a_bias_that_every_run_shares(self):
        rng, _, mask = band(r=24)
        b = rng.standard_normal(mask.shape)
        s = st.stats(self.field(np.broadcast_to(b, (64,) + mask.shape), mask), self.field(b, mask))
        self.assertAlmostEqual(s["bias"], 1.0, places=9)
        self.assertAlmostEqual(s["static"], 1.0, places=9)
        self.assertIsNone(s["rho_t3"])  # no noise to correlate
        self.assertIsNone(s["rho_s8"])

    def test_bias_and_new_noise_every_frame(self):
        rng, _, mask = band(r=24)
        b = rng.standard_normal(mask.shape)
        e = b + rng.standard_normal((128,) + mask.shape)
        s = st.stats(self.field(e, mask), self.field(b + rng.standard_normal(mask.shape), mask))
        self.assertAlmostEqual(s["bias"], 0.5, delta=0.03)
        self.assertAlmostEqual(s["static"], 0.5 + 0.5 / 128, delta=0.03)
        for key in ("rho_t1", "rho_t3", "rho_s8"):
            self.assertLess(abs(s[key]), 0.03, key)

    def test_noise_that_lasts_the_run_but_not_into_another(self):
        rng, _, mask = band(r=24)
        e = rng.standard_normal(mask.shape) + rng.standard_normal((128,) + mask.shape)  # half lasts all 128 frames
        s = st.stats(self.field(e, mask), self.field(rng.standard_normal(mask.shape), mask))  # another run: not it
        self.assertLess(abs(s["bias"]), 0.03)
        self.assertAlmostEqual(s["static"], 0.5, delta=0.03)  # it stands still, but it is noise: not bias
        self.assertAlmostEqual(s["rho_t10"], 0.5, delta=0.03)  # so it is still there 10 frames later
        self.assertAlmostEqual(s["rho_t30"], 0.5, delta=0.03)

    def test_noise_that_fades_over_frames(self):
        rng, _, mask = band(r=24)
        e = np.zeros((256,) + mask.shape)
        e[0] = rng.standard_normal(mask.shape)
        for i in range(1, 256):  # each frame keeps half of the last one's error
            e[i] = 0.5 * e[i - 1] + np.sqrt(0.75) * rng.standard_normal(mask.shape)
        s = st.stats(self.field(e, mask), self.field(rng.standard_normal(mask.shape), mask))
        self.assertAlmostEqual(s["rho_t1"], 0.5, delta=0.03)
        self.assertAlmostEqual(s["rho_t3"], 0.125, delta=0.03)
        self.assertAlmostEqual(s["rho_t10"], 0.0, delta=0.03)

    def test_noise_neighbours_share_over_the_disk(self):
        rng, _, mask = band(r=24)
        w = rng.standard_normal((128, mask.shape[0] + 2, mask.shape[1] + 2))
        n = sum(w[:, i:i + mask.shape[0], j:j + mask.shape[1]] for i in range(3) for j in range(3)) / 3.0  # 3x3 box
        s = st.stats(self.field(n, mask), self.field(rng.standard_normal(mask.shape), mask))
        # the box's overlap with itself shifted by (i, j), over the 196 shifts within 8 pixels: (81 - 9) / 9 / 196
        self.assertAlmostEqual(s["rho_s8"], 8 / 196, delta=0.005)

    def test_a_smooth_bias_is_not_counted_as_neighbours_sharing_noise(self):
        rng, _, mask = band(r=24)
        b = np.cumsum(np.cumsum(rng.standard_normal(mask.shape), axis=0), axis=1)  # smooth: neighbours alike
        b /= b.std()
        e = b + rng.standard_normal((128,) + mask.shape)
        s = st.stats(self.field(e, mask), self.field(b + rng.standard_normal(mask.shape), mask))
        self.assertLess(abs(s["rho_s8"]), 0.03)

    def test_a_band_shorter_than_the_disk_uses_the_offsets_that_fit(self):
        rng, _, mask = band(r=4)
        s = st.stats(self.field(rng.standard_normal((32,) + mask.shape), mask),
                     self.field(rng.standard_normal(mask.shape), mask))
        self.assertLess(abs(s["rho_s8"]), 0.03)  # rows 4 or more apart have no pairs: left out, not wrapped round

    def test_noise_below_the_floor_has_no_correlations(self):
        rng, _, mask = band(r=24)
        b = rng.standard_normal(mask.shape)
        e = b + 0.1 * rng.standard_normal((64,) + mask.shape)  # 1% of the error is noise
        s = st.stats(self.field(e, mask), self.field(b, mask))
        self.assertIsNone(s["rho_t1"])
        self.assertIsNone(s["rho_s8"])
        e = b + 0.33 * rng.standard_normal((64,) + mask.shape)  # 10%: the bias's estimate errs by more than that
        self.assertIsNone(st.stats(self.field(e, mask), self.field(b + 0.33 * rng.standard_normal(mask.shape), mask))
                          ["rho_t3"])


class TestSmape(unittest.TestCase):
    """Junkins et al.'s error measure as their restir-eval computes it (compute_error_measures.smape): per pixel the
    mean over the frames of |s - r| / (|s| + |r| + 1e-4), in percent, on Rec. 709 luminance; here averaged over the
    band's medium."""

    def test_right_is_zero_and_twice_as_bright_is_a_third(self):
        _, ref, mask = band(r=4)
        self.assertEqual(st.smape(np.broadcast_to(ref, (8,) + ref.shape), ref, mask), 0.0)
        self.assertAlmostEqual(st.smape(np.broadcast_to(2 * ref, (8,) + ref.shape), ref, mask), 100 / 3, places=2)

    def test_it_is_restir_evals_formula_over_the_medium_only(self):
        rng, ref, mask = band(r=4)
        strip = ref * (1 + 0.5 * rng.standard_normal((8,) + ref.shape))
        strip[:, ~mask] = 1e3  # far off, outside the medium
        s, r = strip @ np.array([0.2126, 0.7152, 0.0722]), ref @ np.array([0.2126, 0.7152, 0.0722])
        want = float(((np.abs(s - r) / (np.abs(s) + np.abs(r) + 1e-4)).mean(axis=0) * 100.0)[mask].mean())
        self.assertAlmostEqual(st.smape(strip, ref, mask), want, places=9)


class TestRelcov(unittest.TestCase):
    """Junkins et al.'s temporal covariance (restir-eval's relcov): per pixel the noise's covariance with itself three
    frames later over the pixel's value squared, averaged over the band's medium; the bias, which an independent chain
    shares, left out."""

    def test_noise_that_lasts_every_frame_counts_in_full(self):
        rng, ref, mask = band(t=64, r=4)
        lasting = ref * (0.3 * rng.standard_normal(ref.shape))  # the same in every frame, not in the other chain
        strip = np.broadcast_to(ref + lasting, (64,) + ref.shape)
        y = np.array([0.2126, 0.7152, 0.0722])
        mean = (ref + lasting) @ y  # the pixel's mean over the frames, as theirs is over the runs
        want = float(((lasting @ y) ** 2 / (mean + 1e-4) ** 2)[mask].mean())
        self.assertAlmostEqual(st.relcov(strip, ref, mask, ref), want, places=9)  # the other chain right: no bias

    def test_a_pixel_dark_in_the_reference_but_bright_as_rendered_does_not_blow_it_up(self):
        rng, ref, mask = band(t=64, r=4)
        strip = np.array(np.broadcast_to(ref, (64,) + ref.shape))
        dark = ref.copy()
        dark[0, 50] = 1e-6  # a smeared lamp: black in the reference, bright as rendered, every frame
        strip[:, 0, 50] = 0.5 + 0.05 * rng.standard_normal((64, 1))
        self.assertLess(abs(st.relcov(strip, dark, mask, dark)), 0.01)

    def test_fresh_noise_every_frame_has_next_to_none(self):
        rng, ref, mask = band(t=400, r=4)
        strip = ref * (1 + 0.3 * rng.standard_normal((400,) + ref.shape))
        self.assertAlmostEqual(st.relcov(strip, ref, mask, ref), 0.0, delta=0.01)

    def test_a_bias_every_run_shares_is_left_out(self):
        _, ref, mask = band(t=64, r=4)
        biased = ref * 1.2  # a fifth too bright in every frame and in the independent chain alike
        self.assertAlmostEqual(st.relcov(np.broadcast_to(biased, (64,) + ref.shape), ref, mask, biased), 0.0, places=9)


class TestWindow(unittest.TestCase):
    def test_the_window_holds_the_largest_error(self):
        err = np.zeros((8, 400))
        err[:, 250:290] = 1.0  # one bright streak of error
        x0 = st.pick_window(err, 100)
        self.assertTrue(x0 <= 250 and x0 + 100 >= 290)
        self.assertEqual(st.pick_window(err, 400), 0)  # as wide as the band


def off_the_page(fig):
    """Every word on `fig` that runs past its edges, as messages."""
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    page = fig.bbox
    words = [t for t in fig.texts if t.get_text()] + [ax.title for ax in fig.axes if ax.title.get_text()]
    return ["%r runs off the page" % t.get_text() for t in words
            if not (page.x0 <= t.get_window_extent(rend).x0 and t.get_window_extent(rend).x1 <= page.x1
                    and page.y0 <= t.get_window_extent(rend).y0 and t.get_window_extent(rend).y1 <= page.y1)]


class TestGain(unittest.TestCase):
    def test_twice_the_error_half_the_amplification(self):
        ref, inside = np.full((16, 40, 3), 0.4), np.ones(40, bool)
        self.assertEqual(st.gain(ref + 0.0225, ref, inside), 20)  # its 99th percentile to 0.45 from grey
        self.assertEqual(st.gain(ref - 0.045, ref, inside), 10)

    def test_it_counts_the_medium_only(self):
        ref, inside = np.full((16, 40, 3), 0.4), np.ones(40, bool)
        inside[:10] = False
        img = ref + 0.0225
        img[:, :10] += 0.4  # far off, outside the medium
        self.assertEqual(st.gain(img, ref, inside), 20)


class TestNumbers(unittest.TestCase):
    def test_a_panels_numbers(self):
        s = {"energy": 0.171, "static": 0.58, "bias": -0.01, "rho_t3": 0.8149}
        self.assertEqual(st.numbers_line(s), "0.171 · 59% · 0.81")  # relMSE · noise that lasts · its rho at 3
        self.assertEqual(st.numbers_line(dict(s, rho_t3=None)), "0.171 · 59% · —")  # too little noise to tell
        self.assertEqual(st.numbers_line(dict(s, rho_t3=1.013)), "0.171 · 59% · 1.00")  # the bias estimate's error

    def test_lasting_noise_is_never_below_none(self):
        self.assertEqual(st.lasting({"static": 0.98, "bias": 1.01}), 0.0)  # an estimate's noise, not negative noise


class TestPage(unittest.TestCase):
    def lines(self, t=16, w=64, configs=st.CONFIGS):
        rng = np.random.default_rng(1)
        ref = rng.uniform(0.2, 0.8, (w, 3))
        lines, numbers = {}, {}
        for den in st.CHANNELS:
            for hist, m in configs:
                lines[den, hist, m] = ref * (1 + 0.3 * rng.standard_normal((t, w, 3)))
                numbers[den, hist, m] = {"energy": 0.123, "static": 0.45, "bias": 0.2,
                                         "rho_t3": None if den == "rr" else 0.81}
        return ref, lines, numbers

    def test_a_page_is_the_text_width_with_no_words_on_the_pictures_or_off_the_page(self):
        import test_five_figures as tf
        ref, lines, numbers = self.lines()
        frame = np.random.default_rng(2).uniform(0, 1, (40, 64, 3))
        fig = st.page_canvas(frame, (0, 4), (0, 64), ref, np.ones(64, bool), lines, numbers,
                             lambda a: np.clip(a, 0, 1))
        self.assertAlmostEqual(fig.get_size_inches()[0], 7.0)  # placed at the text width, so its fonts print at size
        self.assertLess(fig.get_size_inches()[1], 8.0)  # with its caption, inside the 8.66 in text block
        self.assertEqual(off_the_page(fig), [])
        self.assertEqual(tf.overlaps(fig), [])


def cv2_read(path):
    import m_corr as mc
    return mc.read_exr(path)[..., :3][..., ::-1].astype(np.float64)


def setup_on_disk(root, t=6, h=40, w=200, rows=(10, 14), configs=st.CONFIGS, pick="c200"):
    """A setup with a reference, its medium, a plain run at history `pick` whose chain-0 OptiX frame errs at columns
    120:140 of the band, and the strips of every config in `configs`."""
    import json
    import cv2
    rng = np.random.default_rng(4)
    ref = rng.uniform(0.2, 0.8, (h, w, 3)).astype(np.float32)
    run = "fd_%s_m0" % pick
    for d in ("ref", "noreuse", run):
        os.makedirs(os.path.join(root, "s", d))
    cv2.imwrite(os.path.join(root, "s", "ref", "c.Accum.output.10.exr"), ref[..., ::-1])
    half = ref * (1 + 0.05 * rng.standard_normal(ref.shape)).astype(np.float32)  # its half accumulation
    cv2.imwrite(os.path.join(root, "s", "ref", "c.Accum.output.5.exr"), half[..., ::-1])
    mask = np.ones((h, w), bool)
    mask[:, :20] = False
    np.save(os.path.join(root, "s", "noreuse", "c.medium.npy"), mask)
    chain0 = ref.copy()
    chain0[rows[0]:rows[1], 120:140] *= 3.0
    cv2.imwrite(os.path.join(root, "s", run, "c.optix.801.exr"), chain0[..., ::-1])
    cv2.imwrite(os.path.join(root, "s", run, "c.optix.1602.exr"), ref[..., ::-1])  # chain 1's: no error
    with open(os.path.join(root, "s", run, "c.schedule.json"), "w") as fh:
        json.dump({"channels": {"optix": "optix"}, "chains": [{"frames": [801]}, {"frames": [1602]}]}, fh)
    strips = {}
    for hist, m in configs:
        d = os.path.join(root, "s", "st_fd_%s_m%d" % (hist, m))
        os.makedirs(d)
        with open(os.path.join(d, "c.schedule.json"), "w") as fh:
            json.dump({"channels": {den: "ch_" + den for den in st.CHANNELS},
                       "chains": [{"frames": [801]}, {"frames": [1602]}]}, fh)
        for den in st.CHANNELS:
            strips[den, hist, m] = ref[rows[0]:rows[1]] * (1 + 0.2 * rng.standard_normal((t, rows[1] - rows[0], w, 3)))
            np.save(os.path.join(d, "c.strip.%s.npy" % den), strips[den, hist, m].astype(np.float32))
            for frame in (801, 1602):  # chain 0's capture, independent of the strip; chain 1's, its first frame
                img = ref * (1 + 0.2 * rng.standard_normal(ref.shape)).astype(np.float32)
                cv2.imwrite(os.path.join(d, "c.ch_%s.%d.exr" % (den, frame)), img[..., ::-1])
    results = {"s": {"histories": {pick: {"m0": {"optix": {"run": "s/" + run}}}}}}
    return ref, mask, strips, results


def longer_reference(root, ref):
    """A longer reference run for setup s, 1.1 times as bright as its own (so measures can tell them apart), and
    its half accumulation; returns its folder."""
    import cv2
    d = os.path.join(root, "long_refs", "s", "ref")
    os.makedirs(d)
    cv2.imwrite(os.path.join(d, "c.Accum.output.40.exr"), (ref * 1.1)[..., ::-1])
    cv2.imwrite(os.path.join(d, "c.Accum.output.20.exr"), (ref * 1.12)[..., ::-1])
    return d


class TestScene(unittest.TestCase):
    def test_the_window_where_chain_0_errs_and_the_bands_statistics(self):
        with tempfile.TemporaryDirectory() as root:
            ref, mask, strips, results = setup_on_disk(root)
            sc = st.scene(root, results, "s", (10, 14), width=50)
            x0, x1 = sc.cols
            self.assertEqual(x1 - x0, 50)
            self.assertTrue(x0 <= 120 and x1 >= 140)  # the chain-0 error, not the strips' own noise
            self.assertEqual(sc.err0.shape, (4, 200))  # chain 0's error over the band, kept to choose the
            self.assertTrue(120 <= int(np.argmax(np.nan_to_num(np.abs(sc.err0)).sum(axis=0))) < 140)  # panels'
            strip = strips["optix", "c200", 0].astype(np.float32)
            c0 = cv2_read(os.path.join(root, "s", "st_fd_c200_m0", "c.ch_optix.801.exr"))[10:14]
            rb, mb = ref[10:14].astype(np.float64), mask[10:14]
            want = dict(st.stats(st.error_field(strip, rb, mb), st.error_field(c0[None], rb, mb)[0]),  # against chain 0
                        smape=st.smape(strip, rb, mb), relcov_t3=st.relcov(strip, rb, mb, c0))
            self.assertEqual(sorted(sc.numbers["optix", "c200", 0]), sorted(want))
            for key, value in want.items():
                if value is None:
                    self.assertIsNone(sc.numbers["optix", "c200", 0][key], key)
                else:
                    self.assertAlmostEqual(sc.numbers["optix", "c200", 0][key], value, places=9)
            np.testing.assert_allclose(sc.lines["raw", "ship", 5], strips["raw", "ship", 5].astype(np.float32)[:, 2, x0:x1])
            np.testing.assert_allclose(sc.ref_line, ref[12, x0:x1], rtol=1e-6)  # the band's centre row
            self.assertTrue(sc.inside.all())
            half = cv2_read(os.path.join(root, "s", "ref", "c.Accum.output.5.exr"))
            self.assertAlmostEqual(sc.ref_noise, mm.relmse(half[10:14], ref[10:14].astype(np.float64), mask[10:14]),
                                   places=9)  # the reference's own error in the band: it stands still too

    def test_the_panels_pixels_are_chosen_on_chain_0s_error_as_shown(self):
        import five_figures as ff
        with tempfile.TemporaryDirectory() as root:
            ref, mask, _, results = setup_on_disk(root)
            sc = st.scene(root, results, "s", (10, 14), width=50)
            c0 = cv2_read(os.path.join(root, "s", "fd_c200_m0", "c.optix.801.exr"))[10:14]
        show = ff.display("s", ref.astype(np.float64), mask)
        shown = np.abs(np.clip(show(c0), 0, 1) - np.clip(show(ref[10:14].astype(np.float64)), 0, 1)).mean(axis=-1)
        np.testing.assert_allclose(sc.err0, np.where(mask[10:14], shown, np.nan), rtol=1e-6)  # not where it is clipped

    def test_other_configs_measured_on_a_longer_reference_with_the_window_in_a_view(self):
        import five_figures as ff
        night = (("c50", 0), ("c50", 5))
        with tempfile.TemporaryDirectory() as root:
            ref, mask, _, results = setup_on_disk(root, configs=night, pick="c50")
            long_dir = longer_reference(root, ref)
            sc = st.scene(root, results, "s", (10, 14), width=50, configs=night, pick=("c50", 0), ref_dir=long_dir,
                          within=(20, 100))
            half, full = (cv2_read(os.path.join(long_dir, "c.Accum.output.%d.exr" % n)) for n in (20, 40))
        x0, x1 = sc.cols
        self.assertTrue(20 <= x0 and x1 <= 100)  # inside the view, though chain 0 errs most at 120:140
        self.assertEqual(x1 - x0, 50)
        self.assertEqual(sorted({(h, m) for _, h, m in sc.numbers}), sorted(night))
        np.testing.assert_allclose(sc.ref_line, 1.1 * ref[12, x0:x1], rtol=1e-6)  # measured against the longer one
        self.assertAlmostEqual(sc.ref_noise, mm.relmse(half[10:14], full[10:14], mask[10:14]), places=9)
        grey = np.full((1, 1, 3), 0.3)  # shown as the setup's own reference is (the viewer's, the paper's exposure)
        np.testing.assert_allclose(sc.show(grey), ff.display("s", ref.astype(np.float64), mask)(grey))

    def test_a_missing_strip_is_named(self):
        with tempfile.TemporaryDirectory() as root:
            setup_on_disk(root)
            os.remove(os.path.join(root, "s", "st_fd_ship_m5", "c.strip.rr.npy"))
            with self.assertRaisesRegex(FileNotFoundError, "rr.*ship.*m5"):
                st.scene(root, {"s": {"histories": {"c200": {"m0": {"optix": {"run": "s/fd_c200_m0"}}}}}}, "s",
                         (10, 14), width=50)


class TestOverview(unittest.TestCase):
    def scenes(self, n=3, t=16, w=64, configs=st.CONFIGS):
        """Synthetic setups whose chain 0 errs most at columns 40:48 of the window."""
        page = TestPage()
        out = []
        for i in range(n):
            ref, lines, numbers = page.lines(t, w, configs)
            err0 = np.zeros((4, max(64, w)))
            err0[:, 40:48] = 1.0
            out.append(types.SimpleNamespace(frame=np.random.default_rng(i).uniform(0, 1, (36, max(64, w), 3)),
                                             rows=(10, 14), cols=(0, w), ref_line=ref, inside=np.ones(w, bool),
                                             lines=lines, numbers=numbers, err0=err0, show=lambda a: np.clip(a, 0, 1),
                                             name="scene %d" % i))
        return out

    def numbered(self, scenes):
        for sc in scenes:
            for key in sc.numbers:
                sc.numbers[key] = dict(sc.numbers[key], smape=21.33)
        return scenes

    def panels(self, fig, n=st.XT_N):
        """The (x, t) panels: the axes showing n pixels by n frames, in the order drawn (row by row)."""
        return [ax for ax in fig.axes if ax.images and ax.images[0].get_array().shape[:2] == (n, n)]

    def test_three_setups_at_the_text_width_with_no_words_on_the_pictures_or_off_the_page(self):
        import five_figures as ff
        import test_five_figures as tf
        fig = st.xt_canvas(self.numbered(self.scenes(t=128, w=320)), ("raw", "optix", "rr"))  # none, OptiX, DLSS RR
        self.assertAlmostEqual(fig.get_size_inches()[0], 7.0)
        self.assertLess(fig.get_size_inches()[1], 7.9)  # a page of its own, with room for its caption
        texts = [t.get_text() for t in fig.texts]
        for head in ("M cap 4 (shipped)", "M cap 4", "M cap 200", "No denoiser"):  # every setting, its cap named
            self.assertIn(head, texts)
        self.assertEqual(sum(t == "+ 5 mutations" for t in texts), 2)  # with mutations at both caps
        self.assertEqual(texts.count(st.XT_KEY), 1)  # what the numbers are, said once
        self.assertEqual(texts.count("21.3 · 0.81"), 3 * 2 * 4)  # under each panel but the reference's,
        self.assertEqual(texts.count("21.3 · —"), 3 * 4)  # DLSS RR's a dash (mostly bias)
        self.assertEqual([t.get_color() for t in fig.texts if t.get_text() == "OptiX"], [ff.BLUE] * 3)  # as before
        self.assertEqual(off_the_page(fig), [])
        self.assertEqual(tf.overlaps(fig), [])

    def test_each_panel_is_n_pixels_by_n_frames_in_square_blocks_where_chain_0_errs_most(self):
        sc = self.numbered(self.scenes(1, t=128, w=320))[0]
        fig = st.xt_canvas([sc], ("raw", "optix", "rr"))
        panels = self.panels(fig)
        self.assertEqual(len(panels), 3 * len(st.XT_COLUMNS))  # every panel, the reference's too
        fw, fh = fig.get_size_inches()
        for ax in panels:  # square, so a pixel is as wide as a frame is tall, as Junkins et al.'s
            self.assertAlmostEqual(ax.get_position().width * fw, ax.get_position().height * fh)
        a, b = st.sub_window(sc.cols, sc.err0, st.XT_N)
        self.assertTrue(a <= 40 and 48 <= b)  # the pixels chain 0 errs most on
        optix_c200 = panels[1 * len(st.XT_COLUMNS) + 3]  # OptiX's row, plain ReSTIR at M cap 200
        np.testing.assert_allclose(optix_c200.images[0].get_array(),
                                   np.clip(sc.lines["optix", "c200", 0][:st.XT_N, a:b], 0, 1))  # the first n frames

    def test_the_n_pixels_of_a_window_where_chain_0_errs_most(self):
        err = np.zeros((4, 500))
        err[:, 300:330] = -2.0
        x0, x1 = st.sub_window((100, 420), err, 60)
        self.assertEqual(x1 - x0, 60)
        self.assertTrue(100 <= x0 <= 300 and 330 <= x1 <= 420)

    def test_the_night_street_through_every_channel_in_ink_with_each_rows_numbers_under_it(self):
        import matplotlib.colors as mcolors
        import five_figures as ff
        import test_five_figures as tf
        sc = self.numbered(self.scenes(1, t=128, w=320, configs=(("c50", 0), ("c50", 5))))[0]
        fig = st.xt_canvas([sc], st.NIGHT_DENOISERS, columns=st.NIGHT_COLUMNS, panel=st.NIGHT_PANEL, ink_names=True)
        self.assertAlmostEqual(fig.get_size_inches()[0], 7.0)
        self.assertLess(fig.get_size_inches()[1], 7.9)
        texts = [t.get_text() for t in fig.texts]
        for head in ("Reference", "ReSTIR", "+ 5 mutations", "M cap 50", st.XT_KEY):
            self.assertIn(head, texts)
        names = ("No denoiser", "OptiX", "DLSS RR", "OIDN", "NRD RELAX", "NRD REBLUR")
        for name in names:  # every row named, in ink: the hues past the second are under 3:1 on white
            self.assertEqual([t.get_color() for t in fig.texts if t.get_text() == name], [ff.INK])
        self.assertEqual(texts.count("21.3 · 0.81"), 10)  # under both columns of every row but DLSS RR's,
        self.assertEqual(texts.count("21.3 · —"), 2)  # which is mostly bias here
        self.assertEqual(len(self.panels(fig)), 6 * 3)
        frames = {mcolors.to_hex(ax.spines["left"].get_edgecolor()) for ax in fig.axes if ax.images}
        self.assertTrue({ff.MUTED, ff.BLUE, ff.ORANGE, st.AQUA, st.YELLOW, st.MAGENTA} <= frames)
        self.assertEqual(off_the_page(fig), [])
        self.assertEqual(tf.overlaps(fig), [])

    def test_the_frame_is_cut_full_height_around_the_strip(self):
        self.assertEqual(st.crop_around((1080, 1920), (1162, 1482), 0.8), (890, 1754))  # 864 wide, centred
        self.assertEqual(st.crop_around((540, 960), (0, 160), 0.8), (0, 432))  # held inside the frame
        self.assertEqual(st.crop_around((540, 960), (800, 960), 0.8), (528, 960))


class TestMain(unittest.TestCase):
    def test_it_writes_the_statistics_and_a_page_per_setup(self):
        import json
        with tempfile.TemporaryDirectory() as root:
            _, _, _, results = setup_on_disk(root)
            for d in ("five_denoisers", "figs"):
                os.makedirs(os.path.join(root, d))
            with open(os.path.join(root, "five_denoisers", "results.json"), "w") as fh:
                json.dump(results, fh)
            st.main([root], scenes={"s": (10, 14)})
            with open(os.path.join(root, "five_denoisers", "spacetime.json")) as fh:
                out = json.load(fh)
            self.assertEqual(out["s"]["rows"], [10, 14])
            self.assertEqual(out["s"]["window"], [0, 200])  # the frame is narrower than the window
            self.assertEqual(out["s"]["frames"], 6)
            self.assertEqual(sorted(out["s"]["histories"]), ["c200", "ship"])
            self.assertEqual(sorted(out["s"]["histories"]["c200"]["m5"]), sorted(st.CHANNELS))
            self.assertIn("rho_s8", out["s"]["histories"]["ship"]["m0"]["rr"])
            self.assertIn("bias", out["s"]["histories"]["ship"]["m0"]["rr"])
            self.assertGreater(out["s"]["histories"]["ship"]["m0"]["rr"]["smape"], 0.0)  # Junkins et al.'s error
            self.assertNotIn("rho_t10", out["s"]["histories"]["ship"]["m0"]["rr"])  # 6 frames: no lag of 10
            self.assertGreater(out["s"]["ref_noise"], 0.0)
            self.assertTrue(os.path.exists(os.path.join(root, "figs", "spacetime_s.png")))
            self.assertTrue(os.path.exists(os.path.join(root, "figs", "spacetime.png")))  # the (x, t) figure

    def test_the_night_street_has_a_figure_and_numbers_of_its_own(self):
        import json
        with tempfile.TemporaryDirectory() as root:
            ref, _, _, _ = setup_on_disk(root, configs=st.NIGHT_CONFIGS, pick="c50")
            longer_reference(root, ref)
            results = {"s": {"histories": {"c50": {"m0": {"optix": {"run": "s/fd_c50_m0"}}}}}}
            for d in ("five_denoisers", "figs"):
                os.makedirs(os.path.join(root, d))
            st.night(root, results, "s", (10, 14), view=(20, 100))
            with open(os.path.join(root, "five_denoisers", "spacetime_night.json")) as fh:
                out = json.load(fh)
            self.assertEqual(sorted(out["s"]["histories"]), ["c50"])
            self.assertEqual(sorted(out["s"]["histories"]["c50"]["m5"]), sorted(st.CHANNELS))
            self.assertTrue(20 <= out["s"]["window"][0])
            self.assertTrue(os.path.exists(os.path.join(root, "figs", "spacetime_night.png")))
            self.assertFalse(os.path.exists(os.path.join(root, "figs", "spacetime.png")))  # the paper's left alone


class TestFind(unittest.TestCase):
    def test_raw_from_any_run_of_the_config_and_rr_from_its_own(self):
        with tempfile.TemporaryDirectory() as root:
            for cfg, names in (("st_fd1_c200_m0", ["raw", "optix", "oidn"]), ("st_fd2_c200_m0", ["raw", "relax", "reblur"]),
                               ("st_fr_c200_m0", ["rr"]), ("st_fd1_c200_m5", ["raw"])):
                os.makedirs(os.path.join(root, "s", cfg))
                for n in names:
                    open(os.path.join(root, "s", cfg, "c.strip.%s.npy" % n), "wb").close()
            path = lambda den: st.find_strip(root, "s", "c200", 0, den)  # noqa: E731
            self.assertTrue(path("raw").endswith(os.path.join("st_fd1_c200_m0", "c.strip.raw.npy")))
            self.assertTrue(path("relax").endswith(os.path.join("st_fd2_c200_m0", "c.strip.relax.npy")))
            self.assertTrue(path("rr").endswith(os.path.join("st_fr_c200_m0", "c.strip.rr.npy")))
            self.assertIsNone(st.find_strip(root, "s", "ship", 0, "raw"))


if __name__ == "__main__":
    unittest.main()
