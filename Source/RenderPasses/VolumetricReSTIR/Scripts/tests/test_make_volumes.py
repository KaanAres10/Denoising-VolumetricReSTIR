"""make_volumes.py: the authored volumes' density fields and their raw layout (no tools run).

    python -m unittest test_make_volumes -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import blackbody as bb  # noqa: E402
import make_volumes as mv  # noqa: E402
import volume_boxes as vb  # noqa: E402

COARSE = 0.5  # metres per voxel: the fields' shape, not their detail, at test speed


class TestNoise(unittest.TestCase):
    def test_fbm_is_in_unit_range_and_deterministic(self):
        a = mv.fbm((40, 30, 20), cell=8, octaves=3, seed=5)
        self.assertEqual(a.shape, (40, 30, 20))
        self.assertTrue(0.0 <= a.min() and a.max() <= 1.0)
        self.assertTrue(np.array_equal(a, mv.fbm((40, 30, 20), cell=8, octaves=3, seed=5)))
        self.assertFalse(np.array_equal(a, mv.fbm((40, 30, 20), cell=8, octaves=3, seed=6)))

    def test_fbm_is_smooth_at_its_cell_size(self):
        a = mv.fbm((64, 64, 64), cell=16, octaves=1, seed=1)
        step = np.abs(np.diff(a, axis=0)).mean()
        self.assertLess(step, 0.05 * (a.max() - a.min()))  # white noise would step ~0.33 of its range


class TestFields(unittest.TestCase):
    def test_box_dims(self):
        self.assertEqual(vb.dims("stagehaze"), (260, 100, 220))

    def test_stage_haze_fades_at_the_sides_and_sits_low(self):
        d = mv.stage_haze(voxel=COARSE)
        self.assertEqual(d.shape, mv.shape("stagehaze", COARSE))
        self.assertTrue(0.0 <= d.min() and d.max() <= 1.0)
        for face in (d[0], d[-1], d[:, :, -1]):  # left, right and audience sides: no hard wall of haze
            self.assertLess(face.max(), 1e-3)
        self.assertLess(d[:, -1].max(), 1e-3)  # nor a ceiling
        self.assertGreater(d[:, 2:6].mean(), 1.2 * d[:, 12:16].mean())  # floor (1-3 m) denser than 6-8 m
        self.assertGreater(d.mean(), 0.1)

    def test_ground_mist_hugs_the_ground_and_fades_out_far_away(self):
        d = mv.ground_mist(voxel=COARSE)
        self.assertTrue(0.0 <= d.min() and d.max() <= 1.0)
        self.assertGreater(d[:, :2].mean(), 4 * d[:, 10:].mean())  # below 1 m vs above 5 m
        self.assertLess(d[0].max() + d[-1].max() + d[:, :, 0].max() + d[:, :, -1].max(), 1e-3)
        self.assertGreater(d[:, :2].mean(), 0.05)

    def test_smoke_puffs_sit_on_the_bursts(self):
        d = mv.smoke_puffs(voxel=COARSE)
        lo, _, _ = vb.BOXES["smokepuffs"]
        for c, _ in vb.BURSTS:
            i, j, k = (int((c[a] - lo[a]) / COARSE) for a in range(3))
            self.assertGreater(d[i - 2:i + 3, j - 2:j + 3, k - 2:k + 3].mean(), 0.2, c)
        self.assertLess(d[:4, -4:].max(), 0.05)  # the box's far corner: clear air
        self.assertTrue(0.0 <= d.min() and d.max() <= 1.0)


class TestStudioSky(unittest.TestCase):
    def test_latlong_round_trip_in_falcors_convention(self):
        # Falcor's world_to_latlong_map: u = atan2(x, -z) / 2pi + 0.5, v = acos(y) / pi (u = 0.5 looks down -z)
        for d in ((0.0, 0.0, -1.0), (-0.6, 0.6, 0.5), (0.3, -0.8, 0.1)):
            d = np.array(d) / np.linalg.norm(d)
            u, v = np.arctan2(d[0], -d[2]) / (2 * np.pi) + 0.5, np.arccos(d[1]) / np.pi
            self.assertTrue(np.allclose(mv.latlong_dir(u, v), d, atol=1e-9), d)

    def test_the_soft_box_lands_on_its_direction(self):
        key = np.array([-0.6, 0.6, 0.5])
        sky = mv.studio_sky(key, width=512)
        self.assertEqual(sky.shape, (256, 512, 3))
        j, i = np.unravel_index(np.argmax(sky[..., 0]), sky.shape[:2])
        d = mv.latlong_dir((i + 0.5) / 512, (j + 0.5) / 256)
        self.assertGreater(float(d @ key / np.linalg.norm(key)), np.cos(np.radians(4)))

    def test_ambient_lights_only_the_upper_hemisphere(self):
        key = np.array([-0.6, 0.6, 0.5])
        plain, lit = mv.studio_sky(key, width=512, ambient=0.0), mv.studio_sky(key, width=512, ambient=0.2)
        self.assertTrue(np.allclose(lit[200:], plain[200:]))  # the floor directions: unchanged
        self.assertAlmostEqual(float((lit[20:60] - plain[20:60]).mean()), 0.2 * np.mean([0.9, 0.95, 1.0]), places=3)

    def test_the_studio_floor_is_darker_than_its_walls(self):
        sky = mv.studio_sky(np.array([-0.6, 0.6, 0.5]), width=512)
        self.assertLess(sky[200:, :, 0].mean(), sky[90:120, :, 0].mean())  # below the horizon vs just above
        self.assertGreater(sky.min(), 0.0)


def ring_with_carpet():
    """A z-up dust ring like the EmberGen shockwave's: an annulus r 20-40 voxels, 16 tall, at the data's 0.1 cap,
    and a 3-voxel carpet of dust on the floor of its hole."""
    x, y, z = np.meshgrid(np.arange(100), np.arange(100), np.arange(24), indexing="ij")
    r = np.hypot(x - 50.0, y - 50.0)
    d = np.where((r >= 20) & (r <= 40) & (z < 16), 0.1, 0.0)
    d = np.where((r < 20) & (z < 3), 0.09, d)
    return d.astype(np.float32), r, z


class TestReshapeDust(unittest.TestCase):
    def test_the_hole_radius_is_where_the_ring_wall_rises(self):
        d, _, _ = ring_with_carpet()
        self.assertAlmostEqual(mv.hole_radius(d), 20.0, delta=3.0)

    def test_clearing_the_hole_removes_the_carpet_and_keeps_the_ring(self):
        d, r, z = ring_with_carpet()
        c = mv.clear_hole(d, 20.0, width=4.0)
        self.assertEqual(float(c[r < 15].max()), 0.0)
        self.assertTrue(np.array_equal(c[r > 21], d[r > 21]))

    def test_billows_break_a_thin_bridge_into_round_puffs(self):
        # two balls joined by a thin bridge: at billow scale the bridge goes, the balls stay
        x, y, z = np.meshgrid(np.arange(60), np.arange(30), np.arange(30), indexing="ij")
        ball = lambda cx: (x - cx) ** 2 + (y - 15) ** 2 + (z - 15) ** 2 < 8 ** 2  # noqa: E731
        bridge = (np.hypot(y - 15, z - 15) < 1.5) & (x > 18) & (x < 42)
        d = np.where(ball(15) | ball(45) | bridge, 0.1, 0.0).astype(np.float32)
        b = mv.billows(d, coarse=3.0, level=0.5, softness=0.1, fuzz=0.0)
        self.assertTrue(0.0 <= b.min() and b.max() <= 1.0)
        from scipy import ndimage
        _, n = ndimage.label(b > 0.5)
        self.assertEqual(n, 2)
        self.assertGreater(b[15, 15, 15], 0.9)
        self.assertLess(b[30, 15, 15], 0.1)  # the bridge's middle

    def test_puffs_sit_where_the_dust_is_massed_and_stand_apart(self):
        # two balls that touch, merged at the neck when smoothed: one round puff on each, a gap between them
        x, y, z = np.meshgrid(np.arange(70), np.arange(40), np.arange(40), indexing="ij")
        ball = lambda cx: (x - cx) ** 2 + (y - 20) ** 2 + (z - 20) ** 2 < 11 ** 2  # noqa: E731
        d = np.where(ball(24) | ball(44), 0.1, 0.0).astype(np.float32)
        from scipy import ndimage
        self.assertEqual(ndimage.label(mv.billows(d, coarse=3.0, level=0.5, fuzz=0.0) > 0.5)[1], 1)
        p, centres, _ = mv.puffs(d, scale=4.0, size=2.0)
        self.assertTrue(0.0 <= p.min() and p.max() <= 1.0)
        self.assertEqual(sorted(tuple(c) for c in centres), [(24, 20, 20), (44, 20, 20)])
        self.assertEqual(ndimage.label(p > 0.5)[1], 2)
        self.assertLess(p[34, 20, 20], 0.5)  # the gap where the neck was
        self.assertEqual(float(p[np.sqrt((x - 34.0) ** 2 + (y - 20.0) ** 2 + (z - 20.0) ** 2) > 30].max()), 0.0)

    def test_cauliflower_puffs_add_bumps_on_the_puffs_and_nothing_in_the_gaps(self):
        x, y, z = np.meshgrid(np.arange(70), np.arange(40), np.arange(40), indexing="ij")
        ball = lambda cx: (x - cx) ** 2 + (y - 20) ** 2 + (z - 20) ** 2 < 11 ** 2  # noqa: E731
        rng = np.random.default_rng(2)
        d = np.where(ball(24) | ball(44), 0.1, 0.0).astype(np.float32) * (rng.random((70, 40, 40)) > 0.3)
        plain, _ = mv.puffed(d, scale=4.0, size=2.0, mix=0.0, fuzz=0.0)
        cauli, _ = mv.puffed(d, scale=4.0, size=2.0, mix=0.0, fuzz=0.6, detail_scale=2.0, detail_size=1.5)
        far = np.sqrt((x - 34.0) ** 2 + (y - 20.0) ** 2 + (z - 20.0) ** 2) > 30
        self.assertEqual(float(cauli[far].max()), 0.0)  # no crumbs floating away from the puffs
        self.assertLess(cauli[34, 20, 20], 0.5)  # the gap stays open
        self.assertGreater(np.abs(cauli - plain).max(), 0.2)  # the surfaces changed

    def test_fur_keeps_the_core_and_grows_a_thin_fringe(self):
        # a hard ball (the exported dust is binary at its 0.1 cap): fur keeps its core solid, softens a shell inside its
        # surface and grows partly filled strands out to `reach` voxels beyond it, nothing further
        x, y, z = np.meshgrid(np.arange(60), np.arange(60), np.arange(60), indexing="ij")
        rr = np.sqrt((x - 30.0) ** 2 + (y - 30.0) ** 2 + (z - 30.0) ** 2)
        d = np.where(rr < 15, 0.1, 0.0).astype(np.float32)
        f = mv.fur(d, depth=3.0, reach=4.0, strand=1.5, seed=3)
        self.assertTrue(0.0 <= f.min() and f.max() <= 1.0)
        self.assertGreater(f[rr < 10].min(), 0.99)  # the core
        fringe = (rr > 15.5) & (rr < 18.5)
        filled = (f[fringe] > 0.05).mean()
        self.assertTrue(0.15 < filled < 0.75, filled)  # strands, not a solid shell
        self.assertEqual(float(f[rr > 19.5].max()), 0.0)  # nothing beyond the reach
        self.assertGreater(f[(rr > 12.5) & (rr < 14.5)].std(), 0.05)  # the shell under the surface is broken up too

    def test_fuzz_moves_only_the_edges(self):
        rng = np.random.default_rng(1)
        x, y, z = np.meshgrid(np.arange(40), np.arange(40), np.arange(40), indexing="ij")
        rr = np.sqrt((x - 20.0) ** 2 + (y - 20.0) ** 2 + (z - 20.0) ** 2)
        d = np.where(rr + rng.normal(0, 1.5, rr.shape) < 12, 0.1, 0.0).astype(np.float32)
        smooth, fuzzy = mv.billows(d, coarse=3.0, fuzz=0.0), mv.billows(d, coarse=3.0, fuzz=0.6)
        changed = np.abs(fuzzy - smooth) > 0.05
        self.assertTrue(changed.any())
        self.assertFalse(changed[rr < 6].any() or changed[rr > 18].any())  # not the core, not far outside


class TestCastIron(unittest.TestCase):
    def test_normal_map_is_unit_tileable_and_mostly_up(self):
        n = mv.cast_iron_normals(size=256, seed=4)
        self.assertEqual(n.shape, (256, 256, 3))
        self.assertTrue(np.allclose(np.linalg.norm(n, axis=-1), 1.0, atol=1e-5))
        self.assertGreater(n[..., 2].mean(), 0.9)  # bumps, not a crumpled sheet
        self.assertLess(n[..., 2].min(), 0.95)  # but real bumps
        # seamless: the wrap-around step is no larger than an ordinary neighbour step
        inner = np.abs(np.diff(n, axis=0)).mean()
        seam = np.abs(n[0] - n[-1]).mean()
        self.assertLess(seam, 2.0 * inner)

    def test_feature_size_sets_the_bump_scale(self):
        # broad dents (RenderMan's fractal bump: 0.1..0.8 cm) change little from one texel to the next; grains do
        fine = mv.cast_iron_normals(size=256, seed=4, features=(3, 40))
        broad = mv.cast_iron_normals(size=256, seed=4, features=(16, 120))
        step = lambda n: np.abs(np.diff(n, axis=1)).mean()  # noqa: E731
        self.assertLess(step(broad), 0.5 * step(fine))

    def test_normal_map_encodes_to_8bit_rgb(self):
        rgb = mv.encode_normals(np.array([[[0.0, 0.0, 1.0]]]))
        self.assertEqual(rgb.dtype, np.uint8)
        self.assertEqual(tuple(rgb[0, 0]), (128, 128, 255))


class TestFireLights(unittest.TestCase):
    def test_the_fire_glows_in_renderman_blackbody_floor_colour(self):
        # PxrBlackBody clamps below 1000 K to its table's first knot; the grid's temperatures (0..1.27) all fall there
        self.assertEqual(mv.RMAN_FIRE_RGB, (1.0, 0.008654, 0.0))

    def test_lights_follow_the_flame_density(self):
        flames = np.zeros((20, 20, 20), np.float32)
        flames[4:8, 4:8, 4:8] = 0.1  # 64 voxels: 8/9 of the density
        flames[14:16, 14:16, 14:16] = 0.1  # 8 voxels: 1/9
        table = mv.fire_light_table(flames, n=18, seed=1)
        lights = table["lights"]
        self.assertEqual(len(lights), 18)
        big = sum(all(4 <= c < 8 for c in l["p"]) for l in lights)
        small = sum(all(14 <= c < 16 for c in l["p"]) for l in lights)
        self.assertEqual(big + small, 18)
        self.assertIn(big, (15, 16, 17))  # stratified: the shares to within a light
        self.assertAlmostEqual(sum(l["w"] for l in lights), 1.0, places=6)

    def test_table_carries_the_fires_total_density_and_colour(self):
        flames = np.zeros((6, 6, 6), np.float32)
        flames[2, 3, 4], flames[1, 1, 1] = 0.25, 0.5
        table = mv.fire_light_table(flames, n=3, seed=0)
        self.assertAlmostEqual(table["flames_sum"], 0.75, places=6)
        self.assertEqual(tuple(table["rgb"]), mv.RMAN_FIRE_RGB)


class TestEmissionLights(unittest.TestCase):
    """Point lights standing in for an authored fire's glow: placed by what each voxel emits, in its colour."""

    def setUp(self):
        self.density = np.zeros((16, 16, 16), np.float32)
        self.temp = np.zeros_like(self.density)
        self.density[2:6, 2:6, 2:6], self.temp[2:6, 2:6, 2:6] = 0.5, 1.0  # hot: 3000 K
        self.density[10:14, 10:14, 10:14], self.temp[10:14, 10:14, 10:14] = 0.5, 0.25  # cool: 1237.5 K
        self.density[0, 15, 15] = 1.0  # smoke: no temperature, no glow
        self.kw = dict(cutoff=-650.0 / 2350.0, scale=2350.0, voxel=0.1, sigma_a=0.3, le_scale=2.0)

    def test_lights_sit_where_the_volume_glows(self):
        table = mv.emission_light_table(self.density, self.temp, n=40, seed=3, **self.kw)
        hot = sum(all(2 <= c < 6 for c in l["p"]) for l in table["lights"])
        self.assertGreaterEqual(hot, 39)  # the cool blob emits ~1/1000 as much
        self.assertFalse(any(l["p"] == [0.0, 15.0, 15.0] for l in table["lights"]))

    def test_lights_carry_the_volumes_emission_in_its_colour(self):
        table = mv.emission_light_table(self.density, self.temp, n=40, seed=3, **self.kw)
        rgb3000 = np.array(bb.lut(bb.kelvin(1.0, self.kw['cutoff'], self.kw['scale'])))  # 3000 K
        # what the volume emits: sigma_a x density x LeScale x the LUT, times a voxel's volume, summed
        hot = 64 * 0.3 * 0.5 * 2.0 * rgb3000 * 0.1 ** 3
        cool = 64 * 0.3 * 0.5 * 2.0 * np.array(bb.lut(bb.kelvin(0.25, self.kw['cutoff'], self.kw['scale']))) * 0.1 ** 3
        np.testing.assert_allclose(table["total"], hot + cool, rtol=1e-6)
        Y = np.array([0.2126, 0.7152, 0.0722])
        total_y = sum(np.dot(l["intensity"], Y) for l in table["lights"])
        self.assertAlmostEqual(total_y / np.dot(hot + cool, Y), 1.0, places=6)  # the power, shared out exactly
        l0 = next(l for l in table["lights"] if all(2 <= c < 6 for c in l["p"]))
        np.testing.assert_allclose(np.array(l0["intensity"]) / l0["intensity"][0], rgb3000 / rgb3000[0], rtol=1e-6)


class TestLanternSkies(unittest.TestCase):
    """The green tornadoes' skies (lantern.SKIES; make_volumes.py lantern_sky)."""

    def test_night_sky_is_dark_behind_the_tornado_and_lit_by_its_key(self):
        # the looping tornado's: dark as its preview's backdrop (the Lanterns teal, dimmed), so its thin wisps show,
        # lit by its key from in front
        import lantern
        spec = lantern.SKIES["lantern_night"]
        sky = mv.lantern_sky("lantern_night", width=512)
        d = mv.latlong_dir(((np.arange(512) + 0.5) / 512)[None, :], ((np.arange(256) + 0.5) / 256)[:, None])
        behind = d @ np.array([0.0, 0.0, -1.0]) > np.cos(np.radians(12.0))  # the frame's middle, behind the funnel
        self.assertLess(float(sky[behind].max()), 0.03)
        self.assertGreater(float(sky[behind][..., 1].mean()), float(sky[behind][..., 0].mean()))  # teal
        k = np.asarray(spec["key"]) / np.linalg.norm(spec["key"])
        j, i = np.unravel_index(np.argmax(sky[..., 1] * (d @ k > 0.9)), sky.shape[:2])
        self.assertGreater(float(sky[j, i, 1]), 0.9 * spec["key_radiance"])

    def test_tele_warp_shows_the_wide_lens_sky_in_a_long_lens(self):
        # a long lens sees a few degrees of sky: the sky it shows is the wide lens's, magnified about the view axis
        # (tan of the angle x M inside the cone, as a pinhole frames it), compressed outside, behind it fixed
        M, t1 = 6.0, np.radians(6.0)
        axis = np.array([[0.0, 0.0, -1.0]])
        np.testing.assert_allclose(mv.tele_warp(axis, M, t1), axis, atol=1e-12)
        th = np.radians(3.0)
        d = np.array([[np.sin(th) * np.cos(0.7), np.sin(th) * np.sin(0.7), -np.cos(th)]])
        w = mv.tele_warp(d, M, t1)
        tw = np.arccos(-w[0, 2])
        self.assertAlmostEqual(float(np.tan(tw)), M * np.tan(th), places=6)
        self.assertAlmostEqual(float(np.arctan2(w[0, 1], w[0, 0])), 0.7, places=6)  # its azimuth kept
        np.testing.assert_allclose(mv.tele_warp(np.array([[0.0, 0.0, 1.0]]), M, t1), [[0.0, 0.0, 1.0]], atol=1e-9)
        ang = np.radians(np.linspace(0.5, 179.5, 200))
        dd = np.stack([np.sin(ang), np.zeros_like(ang), -np.cos(ang)], axis=1)
        aw = np.arccos(np.clip(-mv.tele_warp(dd, M, t1)[:, 2], -1, 1))
        self.assertTrue(np.all(np.diff(aw) > 0))  # monotonic: no sky folded over

    def test_lantern_sky_is_still_the_reference_matched_one(self):
        sky = mv.lantern_sky("lantern_sky", width=256)
        self.assertEqual(sky.shape, (128, 256, 3))
        self.assertIn("lantern_sky", mv.SKIES)
        self.assertIn("lantern_night", mv.SKIES)


class TestTornadoDetail(unittest.TestCase):
    """The looping tornado with the Lanterns construct's detail added, its own structure kept (user, 2026-10-17)."""

    def setUp(self):
        yy, xx = np.indices((40, 40), dtype=np.float64)
        r = np.hypot(xx - 20, yy - 20)
        self.d = np.repeat((np.clip(1 - r / 12, 0, 1) * 0.3)[..., None], 60, axis=2).astype(np.float32)  # a column
        self.d[..., :6] = self.d[..., 54:] = 0.0  # clear of the box's faces, as the tornado is

    def test_resampled_finer_with_its_mass_and_place_kept(self):
        # a column many of the warp's noise cells across, as the tornado is (~270 voxels): a warp keeps mass only on
        # average, so on the 24-voxel column one realization is off by up to 12%
        yy, xx = np.indices((100, 100), dtype=np.float64)
        d = np.repeat((np.clip(1 - np.hypot(xx - 50, yy - 50) / 40, 0, 1) * 0.3)[..., None], 60, axis=2).astype(np.float32)
        d[..., :6] = d[..., 54:] = 0.0
        f = mv.tornado_detail(d, up=1.5, specks=0, bands=0.0)
        self.assertEqual(f.shape, (150, 150, 90))
        self.assertEqual(f.dtype, np.float32)
        self.assertAlmostEqual(float(f.sum()) / 1.5 ** 3 / float(d.sum()), 1.0, delta=0.04)
        cx = float((f.sum((1, 2)) * np.arange(150)).sum() / f.sum())
        self.assertAlmostEqual(cx, (50 + 0.5) * 1.5 - 0.5, delta=1.0)  # old voxel 50's centre in the new grid

    def test_warp_breaks_the_smooth_column_into_filaments(self):
        smooth = mv.tornado_detail(self.d, up=1.5, warp=0.0, specks=0, bands=0.0)
        f = mv.tornado_detail(self.d, up=1.5, specks=0, bands=0.0)
        lap = lambda a: float(np.abs(ndimage.laplace(a))[20:40, 20:40, 10:80].mean())  # noqa: E731
        self.assertGreater(lap(f), 3 * lap(smooth))

    def test_bands_wrap_the_axis(self):
        f = mv.tornado_detail(self.d, up=1.0, warp=0.0, specks=0, bands=0.45, pitch=12.0)
        a = np.linspace(0, 2 * np.pi, 64, endpoint=False)
        ring = ndimage.map_coordinates(f[:, :, 30], [20 + 6 * np.cos(a), 20 + 6 * np.sin(a)], order=1)
        self.assertGreater(float(ring.std() / ring.mean()), 0.2)  # varies around the axis (the column: not at all)
        line = f[26, 20, 6:54]  # along the axis at a fixed angle: a band every `pitch` voxels
        spectrum = np.abs(np.fft.rfft(line - line.mean()))
        self.assertAlmostEqual(48 / int(np.argmax(spectrum)), 12.0, delta=2.5)

    def test_specks_are_small_dense_and_inside_the_smoke(self):
        f = mv.tornado_detail(self.d, up=1.0, warp=0.0, bands=0.0, specks=50, speck_density=2.5)
        self.assertGreater(float(f.max()), 2.0)  # far denser than the column's 0.3
        self.assertLess(int((f > 1.0).sum()), 50 * 30)  # each a few voxels
        yy, xx = np.indices((40, 40))
        outside = np.hypot(xx - 20, yy - 20) > 15
        self.assertLess(float(f[outside].max()), 0.05)

    def test_sharp_bands_thin_the_gaps_between_them(self):
        soft = mv.tornado_detail(self.d, up=1.0, warp=0.0, specks=0, bands=0.8, sharp=1.0, pitch=12.0)
        sharp = mv.tornado_detail(self.d, up=1.0, warp=0.0, specks=0, bands=0.8, sharp=3.0, pitch=12.0)
        line = lambda f: f[26, 20, 10:50]  # noqa: E731
        self.assertLess(float(line(sharp).min() / line(sharp).mean()), float(line(soft).min() / line(soft).mean()))
        self.assertAlmostEqual(float(sharp.sum()) / float(soft.sum()), 1.0, delta=0.1)  # the same smoke, regrouped

    def test_specks_vary_in_size_and_density(self):
        f = mv.tornado_detail(np.zeros((40, 40, 60), np.float32) + self.d, up=1.0, warp=0.0, bands=0.0, specks=200,
                              speck_density=2.5, speck_spread=0.6)
        peaks = f[(f == ndimage.maximum_filter(f, size=3)) & (f > 0.6)]
        self.assertGreater(float(np.percentile(peaks, 90) / np.percentile(peaks, 10)), 2.0)

    def test_curl_noise_is_divergence_free(self):
        # the warp's field: a curl, so it swirls the smoke without compressing it (mass kept even on a small subject)
        c = mv.curl_tile(32, 2.5, np.random.default_rng(3))
        div = sum((np.roll(c[a], -1, a) - np.roll(c[a], 1, a)) / 2 for a in range(3))
        mag = np.sqrt(sum(f ** 2 for f in c))
        self.assertLess(float(np.abs(div).mean()), 0.05 * float(mag.mean()))
        f = mv.tornado_detail(self.d, up=1.5, specks=0, bands=0.0)
        self.assertAlmostEqual(float(f.sum()) / 1.5 ** 3 / float(self.d.sum()), 1.0, delta=0.05)

    def test_streaks_run_along_the_swirl(self):
        # the vortex's streaks: long around the axis, thin across it (along z) -- ~6 a turn, so measured at a
        # tornado-like radius (45 voxels; the funnel's is 60-270 on its finer grid)
        yy, xx = np.indices((140, 140), dtype=np.float64)
        d = np.repeat((np.clip(1 - np.hypot(xx - 70, yy - 70) / 60, 0, 1) * 0.3)[..., None], 40, axis=2).astype(np.float32)
        f = mv.tornado_detail(d, up=1.0, warp=0.0, specks=0, bands=0.0, streaks=0.8, streak_width=(3.0, 3.0))
        base = mv.tornado_detail(d, up=1.0, warp=0.0, specks=0, bands=0.0)
        r = f / np.maximum(base, 1e-6)  # the streaks alone
        a = np.linspace(0, 2 * np.pi, 2048, endpoint=False)
        ring = lambda z: ndimage.map_coordinates(r[:, :, z], [70 + 45 * np.cos(a), 70 + 45 * np.sin(a)], order=1)  # noqa: E731
        around = np.mean([np.abs(np.diff(ring(z))).mean() / (2 * np.pi * 45 / 2048) for z in range(10, 30, 4)])
        along_z = float(np.abs(np.diff(r[115, 70, 5:35])).mean())
        self.assertLess(around, 0.3 * along_z)

    def test_erosion_carves_the_thin_smoke_and_keeps_the_core(self):
        base = mv.tornado_detail(self.d, up=1.0, warp=0.0, specks=0, bands=0.0)
        f = mv.tornado_detail(self.d, up=1.0, warp=0.0, specks=0, bands=0.0, erode=0.6, erode_ref=0.15)
        thin, core = (base > 0.01) & (base < 0.06), base > 0.2
        self.assertGreater(float((f[thin] < 0.25 * base[thin]).mean()), 0.3)  # much of the thin smoke carved away
        self.assertGreater(float((f[core] / base[core]).min()), 0.95)  # the dense core untouched
        self.assertGreater(float((f[thin] > 0.75 * base[thin]).mean()), 0.05)  # wisps left standing

    def test_grain_roughens_the_smoke_finely(self):
        base = mv.tornado_detail(self.d, up=1.0, warp=0.0, specks=0, bands=0.0)
        f = mv.tornado_detail(self.d, up=1.0, warp=0.0, specks=0, bands=0.0, grain=0.3)
        r = (f / np.maximum(base, 1e-6))[base > 0.1]
        self.assertGreater(float(r.std()), 0.15)
        self.assertAlmostEqual(float(r.mean()), 1.0, delta=0.05)

    def test_is_repeatable(self):
        np.testing.assert_array_equal(mv.tornado_detail(self.d, specks=20), mv.tornado_detail(self.d, specks=20))


class TestGvdbAtlas(unittest.TestCase):
    """The brick atlas gImportVDB builds must fit SceneGVDB's two Texture3D parts (each at most 2048 deep)."""

    def test_atlas_depth_counts_occupied_bricks(self):
        d = np.zeros((64, 64, 72), np.float32)
        self.assertEqual(mv.gvdb_atlas_depth(d), 0)
        d[3, 3, 3] = 1.0
        self.assertEqual(mv.gvdb_atlas_depth(d), 10)  # one 8^3 brick: a layer of 16 x 16, 10 texels deep
        d[:, :, :] = 1e-5  # below VolFromRaw's cutoff: no bricks
        self.assertEqual(mv.gvdb_atlas_depth(d), 0)
        d[:, :, 64:] = 1.0  # 8 x 8 x 1 bricks, the last layer a partial block
        d[:, :, :8] = 1.0  # another 64
        self.assertEqual(mv.gvdb_atlas_depth(d), 10)  # 128 bricks: one layer
        d[:, :, 8:16] = 1.0  # 192
        d[:, :, 16:24] = 1.0  # 256
        d[:, :, 24:32] = 1.0  # 320: a second layer
        self.assertEqual(mv.gvdb_atlas_depth(d), 20)
        self.assertGreater(mv.GVDB_ATLAS_MAX, 4000)


@unittest.skipUnless((mv.RELEASE / "VolFromRaw.exe").exists() and (mv.RELEASE / "VdbToRaw.exe").exists(), "needs the tools")
class TestBifrostClean(unittest.TestCase):
    """A Bifrost frame rewritten for gImportVDB (bifrost_export.py writes them): its fog density and temperature as
    `density` and `temperature`, in its own index placement, the temperature clipped to the smoke."""

    def test_motion_blur_averages_frames_over_their_common_box(self):
        # volume motion blur as frames averaged (the reference's streaks along its rotation): a blob moving 2 voxels
        # along x between two frames comes out as both halves, each at half its density, over the union of the boxes
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            srcs = []
            for k, x0 in enumerate((0, 2)):
                d = np.zeros((4, 3, 3), np.float32)
                d[1:3, 1, 1] = 1.0
                temp = np.full(d.shape, 300.0, np.float32)
                mv.write_raw(d, t / "d.raw")
                mv.write_raw(temp, t / "t.raw")
                src = t / ("f%d.vdb" % k)
                mv.run([mv.RELEASE / "VolFromRaw.exe", t / "d.raw", 4, 3, 3, 0.1, src, 1e-4, t / "t.raw", x0, 0, 0], cwd=mv.RELEASE)
                srcs.append(src)
            lo, shape, voxel = mv.blur_bifrost_frames(srcs, t / "blur.vdb", density="density", temperature="temperature")
            self.assertEqual(lo, [1, 1, 1])
            self.assertEqual(shape, (4, 1, 1))  # voxels x 1..4: frame 0's 1-2 and frame 1's 3-4
            lo2, box = mv.read_vdb_box(t / "blur.vdb", ("density",))
            np.testing.assert_allclose(box["density"].ravel(), [0.5, 0.5, 0.5, 0.5])

    def test_velocity_blur_of_a_frame_smears_past_its_box(self):
        # one frame blurred along its own velocity (blur_bifrost_velocity): a blob moving 10 voxels a second along x,
        # a 0.5 s shutter -- smeared 5 voxels, its box grown to hold the smear, its mass kept
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            d = np.zeros((4, 3, 3), np.float32)
            d[1:3, 1, 1] = 1.0
            temp = np.full(d.shape, 300.0, np.float32)
            v = np.zeros(d.shape + (3,), np.float32)
            v[..., 0] = 10.0 * 0.1  # m/s, voxel 0.1 m
            mv.write_raw(d, t / "d.raw")
            mv.write_raw(temp, t / "t.raw")
            v.tofile(str(t / "v.raw"))
            src = t / "f.vdb"
            mv.run([mv.RELEASE / "VolFromRaw.exe", t / "d.raw", 4, 3, 3, 0.1, src, 1e-4, t / "t.raw", 0, 0, 0, t / "v.raw"],
                   cwd=mv.RELEASE)
            lo, shape, voxel = mv.blur_bifrost_velocity(src, t / "blur.vdb", shutter=0.5, steps=16, density="density",
                                                        temperature="temperature", velocity="velocity")
            self.assertAlmostEqual(voxel, 0.1, places=6)
            lo2, box = mv.read_vdb_box(t / "blur.vdb", ("density",))
            b = box["density"]
            self.assertAlmostEqual(float(b.sum()), 2.0, delta=0.05)
            along = np.flatnonzero(b.sum((1, 2)) > 1e-3) + lo2[0]
            self.assertLessEqual(int(along.min()), -1)  # past the frame's own box (x 1..2): 2.5 voxels each way
            self.assertGreaterEqual(int(along.max()), 4)
            self.assertEqual(int((b.sum((0, 2)) > 1e-3).sum()), 1)  # nothing across the flow
            # its steps, unless given, from the longest smear (a step every 2 voxels): no copies in a long shutter
            self.assertEqual(mv.blur_steps(v_max=1.0, shutter=0.5, voxel=0.1), 16)  # 5 voxels: the floor
            self.assertEqual(mv.blur_steps(v_max=3.0, shutter=0.8, voxel=0.025), 48)  # 96 voxels
            # a frame exported without its temperature: the density alone
            mv.blur_bifrost_velocity(src, t / "dens.vdb", shutter=0.5, density="density", temperature=None, velocity="velocity")
            lo3, box3 = mv.read_vdb_box(t / "dens.vdb", ("density",))
            np.testing.assert_allclose(box3["density"], b, atol=1e-6)
            with self.assertRaises(SystemExit):
                mv.vdb_grid(t / "dens.vdb", "temperature")

    def test_detail_before_the_blur(self):
        # film detail added to the frame before it is blurred (pre_fine): the blurred frame differs, its mass kept
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            zz, yy, xx = np.indices((24, 30, 24), dtype=np.float64)
            d = np.clip(7.0 - np.hypot(xx - 12, zz - 12), 0.0, 1.0).astype(np.float32).transpose(2, 1, 0).copy()
            d[:, :6] = d[:, 24:] = 0.0  # (room round it: the warp reaches past its ends)
            v = np.zeros(d.shape + (3,), np.float32)
            v[..., 0] = 1.0
            mv.write_raw(d, t / "d.raw")
            v.tofile(str(t / "v.raw"))
            src = t / "f.vdb"
            mv.run([mv.RELEASE / "VolFromRaw.exe", t / "d.raw", *d.shape, 0.1, src, 1e-4, "-", 0, 0, 0, t / "v.raw"], cwd=mv.RELEASE)
            kw = dict(shutter=0.2, density="density", temperature=None, velocity="velocity")
            mv.blur_bifrost_velocity(src, t / "a.vdb", **kw)
            mv.blur_bifrost_velocity(src, t / "b.vdb", pre_fine={"warp": (1.5, 0.8), "warp_scales": (6.0, 3.0), "grain": 0.5,
                                                                   "grain_scale": 2.0}, **kw)
            a = mv.read_vdb_box(t / "a.vdb", ("density",))[1]["density"]
            b = mv.read_vdb_box(t / "b.vdb", ("density",))[1]["density"]
            self.assertAlmostEqual(float(b.sum()), float(a.sum()), delta=0.1 * float(a.sum()))
            n = min(a.size, b.size)
            self.assertGreater(float(np.abs(np.sort(a.ravel())[-n:] - np.sort(b.ravel())[-n:]).mean()), 1e-3)

    def test_flow_streaks_run_along_the_flow(self):
        # fine noise blurred along the velocity and brought back to full contrast: a texture of fine lines along the
        # flow -- smooth along it, varying across it
        v = np.zeros((40, 40, 40, 3), np.float32)
        v[..., 2] = 40.0  # 40 voxels a second along z (voxel 1)
        n = mv.flow_streaks((40, 40, 40), v, 1.0, shutter=0.5, cell=1.5, seed=0)
        self.assertAlmostEqual(float(n.std()), 1.0, delta=0.05)
        c = n[10:30, 10:30, 10:30]
        along = float(np.corrcoef(c[:, :, 1:].ravel(), c[:, :, :-1].ravel())[0, 1])  # neighbours along the flow
        across = float(np.corrcoef(c[1:, :, :].ravel(), c[:-1, :, :].ravel())[0, 1])  # and across it
        self.assertLess(1.0 - along, 0.2 * (1.0 - across))  # far smoother along the flow than across it

    def test_drift_and_grain(self):
        # the construct moving as a whole during the shutter (`drift`, m/s, the volume's frame): a still blob smeared
        # along it; `grain`: fine density variation the blur draws into streaks, the mass kept
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            d = np.zeros((5, 5, 5), np.float32)
            d[2, 2, 2] = 1.0
            v = np.zeros(d.shape + (3,), np.float32)
            mv.write_raw(d, t / "d.raw")
            v.tofile(str(t / "v.raw"))
            src = t / "f.vdb"
            mv.run([mv.RELEASE / "VolFromRaw.exe", t / "d.raw", 5, 5, 5, 0.1, src, 1e-4, "-", 0, 0, 0, t / "v.raw"], cwd=mv.RELEASE)
            mv.blur_bifrost_velocity(src, t / "b.vdb", shutter=0.5, density="density", temperature=None, velocity="velocity",
                                     drift=(0.0, 1.0, 0.0))  # 10 voxels a second along y: 5 over the shutter
            lo, box = mv.read_vdb_box(t / "b.vdb", ("density",))
            b = box["density"]
            ys = np.flatnonzero(b.sum((0, 2)) > 1e-3) + lo[1]
            self.assertGreaterEqual(int(ys.max() - ys.min()), 4)
            self.assertEqual(int((b.sum((1, 2)) > 1e-3).sum()), 1)  # nothing across it
            self.assertAlmostEqual(float(b.sum()), 1.0, delta=0.05)
        g = mv.grain(np.ones((24, 24, 24), np.float32), amplitude=0.6, cell=3.0, seed=0)
        self.assertGreater(float(g.std()), 0.15)
        self.assertAlmostEqual(float(g.mean()), 1.0, delta=0.05)
        self.assertGreaterEqual(float(g.min()), 0.0)

    def test_rewrites_names_keeps_placement_and_clips_temperature(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            d = np.zeros((6, 5, 4), np.float32)
            d[1:5, 1:4, 1:3] = 0.5  # the smoke
            temp = np.full(d.shape, 300.0, np.float32)  # ambient temperature everywhere, as Bifrost leaves it
            temp[2, 2, 1] = 1500.0
            mv.write_raw(d, t / "d.raw")
            mv.write_raw(temp, t / "t.raw")
            src = t / "bifrost.vdb"
            mv.run([mv.RELEASE / "VolFromRaw.exe", t / "d.raw", 6, 5, 4, 0.1, src, 1e-4, t / "t.raw", -10, 3, 7], cwd=mv.RELEASE)
            # (VolFromRaw names them density / temperature; a Bifrost frame's are voxel_fog_density / voxel_temperature)
            lo, shape, voxel = mv.clean_bifrost_vdb(src, t / "clean.vdb", density="density", temperature="temperature")
            self.assertEqual(lo, [-9, 4, 8])  # the smoke's box, where it was
            self.assertEqual(shape, (4, 3, 2))
            self.assertAlmostEqual(voxel, 0.1, places=6)  # Bifrost's, reported; the rewrite is a voxel a unit
            self.assertAlmostEqual(mv.vdb_grid(t / "clean.vdb", "density")[2], 1.0)
            lo2, box = mv.read_vdb_box(t / "clean.vdb", ("density", "temperature"))
            self.assertEqual(lo2, [-9, 4, 8])
            np.testing.assert_allclose(box["density"], 0.5)
            self.assertEqual(box["temperature"].shape, (4, 3, 2))  # clipped to the smoke, not the ambient domain
            self.assertEqual(float(box["temperature"][1, 1, 0]), 1500.0)


@unittest.skipUnless((mv.RELEASE / "VolFromRaw.exe").exists() and (mv.RELEASE / "VdbToRaw.exe").exists(), "needs the tools")
class TestVelocityGrid(unittest.TestCase):
    """A vector grid (Bifrost's voxel_velocity) read back as an array with its components last."""

    def test_velocity_round_trips(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            d = np.ones((3, 2, 2), np.float32)
            v = np.zeros((3, 2, 2, 3), np.float32)
            v[..., 0] = 1.5
            v[1, 1, 1] = (0.25, -2.0, 3.0)
            mv.write_raw(d, t / "d.raw")
            v.tofile(str(t / "v.raw"))  # x slowest, the components fastest
            mv.run([mv.RELEASE / "VolFromRaw.exe", t / "d.raw", 3, 2, 2, 0.05, t / "f.vdb", 1e-4, "-", 4, 5, 6, t / "v.raw"],
                   cwd=mv.RELEASE)
            lo, arr, voxel = mv.vdb_grid(t / "f.vdb", "velocity")
            self.assertEqual(lo, [4, 5, 6])
            self.assertEqual(arr.shape, (3, 2, 2, 3))
            np.testing.assert_allclose(arr, v)
            self.assertAlmostEqual(voxel, 0.05, places=6)
            lo_d, arr_d, _ = mv.vdb_grid(t / "f.vdb", "density")  # the density as it was
            self.assertEqual(arr_d.shape, (3, 2, 2))


class TestVelocityBlur(unittest.TestCase):
    """Volume motion blur along the velocity, as a production renderer blurs a volume (its density looked up at
    x - v(x) t over the shutter): smooth streaks along the flow -- rings where the construct only spins."""

    def setUp(self):
        self.d = np.zeros((41, 9, 41), np.float32)
        self.d[28:31, 3:6, 19:22] = 1.0  # a small blob, 9 voxels right of the middle (x 29, z 20)

    def test_still_smoke_is_left_alone(self):
        v = np.zeros(self.d.shape + (3,), np.float32)
        np.testing.assert_allclose(mv.velocity_blur(self.d, v, 1.0, shutter=0.5, steps=8), self.d, atol=1e-6)

    def test_uniform_flow_smears_along_it_keeping_the_mass(self):
        v = np.zeros(self.d.shape + (3,), np.float32)
        v[..., 2] = 8.0  # 8 voxels a second along z (voxel 1)
        b = mv.velocity_blur(self.d, v, 1.0, shutter=1.0, steps=17)
        self.assertAlmostEqual(float(b.sum()), float(self.d.sum()), delta=0.02 * float(self.d.sum()))
        prof_z = b.sum((0, 1))
        span = np.flatnonzero(prof_z > 1e-3)
        self.assertGreaterEqual(span.max() - span.min(), 9)  # 3 voxels long, smeared over the shutter's 8
        np.testing.assert_allclose(b.sum((1, 2)), self.d.sum((1, 2)), atol=1e-3)  # nothing across the flow

    def test_spin_smears_round_the_axis_not_across_it(self):
        x, z = np.meshgrid(np.arange(41) - 20.0, np.arange(41) - 20.0, indexing="ij")
        v = np.zeros(self.d.shape + (3,), np.float32)
        v[..., 0] = (-z)[:, None, :]  # a solid-body spin about the y axis through (20, 20), 1 rad/s
        v[..., 2] = x[:, None, :]
        b = mv.velocity_blur(self.d, v, 1.0, shutter=1.0, steps=17)
        w = b.sum(1)
        r = np.sqrt(x ** 2 + z ** 2)
        mean_r = float((w * r).sum() / w.sum())
        self.assertAlmostEqual(mean_r, 9.0, delta=1.0)  # still at its radius
        theta = np.arctan2(z, x)
        spread = float(np.sqrt((w * theta ** 2).sum() / w.sum()))
        self.assertGreater(spread, 0.2)  # smeared ~1 radian round the axis (a 3-voxel blob spans ~0.3)

    def test_finer_density_than_velocity(self):
        # a refined volume (post_refine_aero leaves the velocity at the simulation's resolution): the velocity
        # sampled where each density voxel is, by its own voxel size
        v = np.zeros((21, 5, 21, 3), np.float32)
        v[..., 2] = 4.0  # 4 m/s along z on a grid of 2 m voxels
        a = mv.velocity_blur(self.d, v, 1.0, shutter=1.0, steps=17, v_voxel=2.0)
        v_fine = np.zeros(self.d.shape + (3,), np.float32)
        v_fine[..., 2] = 4.0
        np.testing.assert_allclose(a, mv.velocity_blur(self.d, v_fine, 1.0, shutter=1.0, steps=17), atol=1e-5)


class TestTail(unittest.TestCase):
    """The construct's tail as the reference's: its near part soft (out of focus) and wrapped in a pale mist."""

    def test_fit_column_finds_its_cap_and_width(self):
        d = np.zeros((21, 40, 21), np.float32)
        d[6:15, 2:30, 6:15] = 1.0  # a 9-voxel square column standing on y = 2, its top y = 29
        grid = mv.fit_column(d, lo=[-10, 0, -10], off=(0.0, 0.0, 0.0), fit={"diameter": 18.0, "tau": 4.5})
        np.testing.assert_allclose(grid["base"], [0.5, 30.0, 0.5])  # its cap: its axis's top, .vbx coordinates
        self.assertAlmostEqual(grid["density_scale"], 0.5)  # 9 voxels across at density 1: 4.5
        self.assertGreater(grid["scale"], 1.5)

    def test_defocus_softens_only_what_is_out_of_focus(self):
        d = np.zeros((40, 21, 21), np.float32)  # (room round them: the caller pads for the spread)
        d[5, 10, 10] = d[34, 10, 10] = 1.0  # a near speck (x 5) and one in focus (x 34)
        depth = np.broadcast_to(np.arange(40, dtype=np.float32)[:, None, None], d.shape)  # depth grows with x
        b = mv.defocus(d, depth, focus=30.0, ramp=20.0, sigma_max=2.0)
        self.assertAlmostEqual(float(b[34, 10, 10]), 1.0, places=5)  # in focus: as it was
        self.assertLess(float(b[5, 10, 10]), 0.2)  # out of focus: spread
        self.assertAlmostEqual(float(b[:20].sum()), 1.0, delta=0.02)  # its mass kept

    def test_construct_detail_on_a_y_up_column(self):
        # tornado_detail (its axis along z) applied to the Bifrost column (its axis along y), at its own resolution:
        # the same box, fine structure added inside the smoke, nothing far outside it
        zz, yy, xx = np.indices((32, 48, 32), dtype=np.float64)
        r = np.hypot(xx - 16, zz - 16)
        d = np.clip(9.0 - r, 0.0, 1.0).astype(np.float32).transpose(2, 1, 0).copy()  # x slowest, y up
        out = mv.construct_detail(d, warp=(1.5, 0.8), warp_scales=(8.0, 4.0), grain=0.5, grain_scale=2.0, erode=0.3)
        self.assertEqual(out.shape, d.shape)
        core = np.hypot(np.arange(32)[:, None] - 16, np.arange(32)[None, :] - 16) < 6
        self.assertGreater(float(out[:, 10:38, :][core[:, None, :].repeat(28, 1)].std()), 0.05)  # textured
        self.assertLess(float(out[:2].max()), 1e-3)  # nothing at the box's far side

    def test_warp_churns_the_tail_and_spares_the_head(self):
        # the tail's helical bands broken into clumps: the density displaced by smooth noise below `top` of its height
        d = np.zeros((30, 60, 30), np.float32)
        d[10:20, 0:60, 10:20] = 1.0
        d[:, ::6, :] *= 0.2  # bands across it
        np.testing.assert_array_equal(mv.warp(d, amplitude=0.0, cell=8.0, top=0.5, seed=0), d)
        w = mv.warp(d, amplitude=4.0, cell=8.0, top=0.5, seed=0)
        np.testing.assert_allclose(w[:, 45:], d[:, 45:], atol=1e-5)  # its head as it was
        self.assertGreater(float(np.abs(w[:, :20] - d[:, :20]).mean()), 0.05)  # its tail moved
        self.assertAlmostEqual(float(w.sum()), float(d.sum()), delta=0.05 * float(d.sum()))

    def test_mist_wraps_the_tail_thinly(self):
        d = np.zeros((40, 60, 40), np.float32)
        d[15:25, 0:60, 15:25] = 1.0  # a column, y up
        m = mv.mist(d, amplitude=0.05, cell=6.0, reach=6.0, top=0.4, seed=0)
        added = m - d
        self.assertGreaterEqual(float(added.min()), 0.0)
        self.assertLessEqual(float(added.max()), 0.05 + 1e-6)
        low, high = added[:, :20].sum(), added[:, 40:].sum()
        self.assertGreater(float(low), 10.0 * float(high) + 1e-6)  # round its tail, not its head
        outside = added.copy()
        outside[15:25, :, 15:25] = 0.0
        self.assertGreater(float(outside.sum()), 0.5 * float(added.sum()))  # outside the column: a veil

class TestFadeFoot(unittest.TestCase):
    """The construct's foot thinned into smoke (the Lanterns reference's tail): a simulated column is densest at its
    source, on the ground -- far denser than the rest once its tail dissipates -- so its bottom is faded in over a
    fraction of its height."""

    def setUp(self):
        self.d = np.zeros((5, 24, 5), np.float32)
        self.d[1:4, 2:22, 1:4] = 1.0  # a column standing on y = 2, its top y = 21: 20 slices

    def test_bottom_faded_top_untouched(self):
        f = mv.fade_foot(self.d, 0.0, 0.25)
        prof = f[2, :, 2]
        self.assertEqual(float(prof[2]), 0.0)  # its foot, gone
        np.testing.assert_array_equal(f[:, 7:, :], self.d[:, 7:, :])  # above a quarter of its height: as it was
        self.assertTrue(np.all(np.diff(prof[2:8]) > 0))  # faded in smoothly
        self.assertEqual(f.dtype, np.float32)

    def test_floor_keeps_some_smoke(self):
        f = mv.fade_foot(self.d, 0.0, 0.25, floor=0.2)
        self.assertAlmostEqual(float(f[2, 2, 2]), 0.2, places=6)

    def test_column_found_above_a_faint_ground_haze(self):
        d = self.d.copy()
        d[:, 0, :] = 1e-4  # haze far below 2% of the column's slices
        f = mv.fade_foot(d, 0.0, 0.25)
        np.testing.assert_array_equal(f[:, 7:, :], d[:, 7:, :])


class TestGlitter(unittest.TestCase):
    """The construct's glitter (the Lanterns reference's sparkles): points on the volume's surface where it faces the
    key light -- a speck of smoke cannot be brighter than the light reaching it, so the glints are tiny emitters."""

    def setUp(self):
        zz, yy, xx = np.indices((40, 40, 40), dtype=np.float64)
        r = np.sqrt((xx - 20) ** 2 + (yy - 20) ** 2 + (zz - 20) ** 2)
        self.d = np.clip(12.0 - r, 0.0, 1.0).astype(np.float32).transpose(2, 1, 0)  # a ball (x slowest), radius ~12

    def test_points_lie_on_the_surface_facing_the_key(self):
        pts = mv.glitter_points(self.d, n=300, key=(0.0, 1.0, 0.0), threshold=0.5, seed=0)
        self.assertEqual(pts.shape, (300, 3))
        r = np.linalg.norm(pts - 20.0, axis=1)
        self.assertTrue(np.all(np.abs(r - 11.5) < 1.5), (r.min(), r.max()))  # on the ball's surface
        self.assertGreater(float(np.mean(pts[:, 1] > 20.0)), 0.95)  # on the side facing +y, the key

    def test_only_where_the_key_reaches(self):
        # a slab over half the ball's key-facing side shades it: with the smoke's optical depth given, the glitter
        # keeps to where the key's light lands (the reference's sparkles are on its lit side only)
        d = self.d.copy()
        d[:20, 34:37, :] = 0.4  # a slab above the ball's x < 20 half, between it and the key (+y): thin smoke, no glitter of its own
        pts = mv.glitter_points(d, n=200, key=(0.0, 1.0, 0.0), threshold=0.5, seed=0, tau_scale=5.0, pool=1)
        on_ball = pts[np.linalg.norm(pts - 20.0, axis=1) < 14.0]
        self.assertEqual(len(on_ball), 200)  # (the slab is too thin to glitter)
        self.assertGreater(float(np.mean(on_ball[:, 0] >= 19.5)), 0.95)  # the unshaded half
        free = mv.glitter_points(d, n=200, key=(0.0, 1.0, 0.0), threshold=0.5, seed=0)
        free = free[np.linalg.norm(free - 20.0, axis=1) < 14.0]
        self.assertLess(float(np.mean(free[:, 0] >= 19.5)), 0.8)  # without it, both halves

    def test_particles_lie_in_the_smoke_on_its_lit_visible_side(self):
        # glitter as particles in the smoke: drawn by density, kept where the key's light reaches them (+y) and the
        # camera sees them (far along -x): in a dense ball, the quarter facing both
        cam = np.array([-1000.0, 20.0, 20.0])
        pts = mv.glitter_particles(self.d, n=300, key=(0.0, 1.0, 0.0), tau_scale=3.0, camera=cam, seed=0, pool=1)
        self.assertEqual(pts.shape, (300, 3))
        self.assertTrue(np.all(np.linalg.norm(pts - 20.0, axis=1) < 12.5))  # inside the ball
        self.assertGreater(float(np.mean(pts[:, 1] > 20.0)), 0.9)  # lit
        self.assertGreater(float(np.mean(pts[:, 0] < 20.0)), 0.9)  # seen

    def test_particles_through_a_screen_weight(self):
        # an art-directed mask (the reference's sparkle density where each particle shows): none where it is 0
        pts = mv.glitter_particles(self.d, n=200, key=(0.0, 1.0, 0.0), tau_scale=0.0, seed=1, pool=1,
                                   weight=lambda p: (p[:, 2] >= 20.0).astype(float))
        self.assertTrue(np.all(pts[:, 2] >= 19.0))
        again = mv.glitter_particles(self.d, n=200, key=(0.0, 1.0, 0.0), tau_scale=0.0, seed=1, pool=1,
                                     weight=lambda p: (p[:, 2] >= 20.0).astype(float))
        np.testing.assert_array_equal(pts, again)  # seeded

    def test_many_particles_keep_to_a_small_mask(self):
        # more particles than candidates the mask favours: they crowd its favoured smoke (drawn with replacement, each
        # jittered in its voxel), not spill over the rest of the smoke at the mask's floor
        weight = lambda p: 0.001 + ((p[:, 0] > 26.0) & (p[:, 2] > 26.0)).astype(float)  # noqa: E731  a small corner
        pts = mv.glitter_particles(self.d, n=3000, key=(0.0, 1.0, 0.0), tau_scale=0.0, seed=0, pool=1, candidates=2000,
                                   weight=weight)
        self.assertEqual(len(pts), 3000)
        self.assertGreater(float(np.mean((pts[:, 0] > 25.5) & (pts[:, 2] > 25.5))), 0.85)
        self.assertGreater(len(np.unique(np.round(pts, 3), axis=0)), 2900)  # jittered apart

    def test_glint_sprite_is_soft_and_round(self):
        # a glint's emission over its quad: brightest in the middle in the glitter's colour, fading to nothing at the
        # edges, the same every way round
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "glint.png"
            mv.glitter_sprite(path, (0.3, 1.0, 0.42), sigma=0.2, size=33)
            import cv2
            im = cv2.imread(str(path))[..., ::-1].astype(float)  # rgb
            self.assertEqual(im.shape, (33, 33, 3))
            self.assertEqual(int(im[16, 16, 1]), 255)
            self.assertAlmostEqual(im[16, 16, 0] / 255.0, 0.3, delta=0.01)
            self.assertLess(float(im[0, 0].max()), 3.0)
            self.assertAlmostEqual(float(im[16, 6, 1]), float(im[6, 16, 1]), delta=1.0)

    def test_glint_sprays_are_soft_and_streaked(self):
        # a soft glint as a spray of sub-pixel micro-glints (a big quad would hide the smoke behind it): Gaussian
        # round its centre in the camera's plane, `width` x its size across, spread evenly along its motion
        cam = {"position": (0.0, 0.0, 52.0), "target": (0.0, 0.0, 0.0), "focal": 50.0}
        pts = mv.glint_sprays(np.array([[0.0, 0.0, 0.0], [5.0, 0.0, 0.0]]), [0.2, 0.2], [[0.0, 1.0, 0.0], [0.0, 0.0, 0.0]],
                              cam, per=400, width=0.25, seed=0)
        self.assertEqual(pts.shape, (800, 3))
        a, b = pts[:400], pts[400:]
        self.assertAlmostEqual(float(np.std(b[:, 0])), 0.05, delta=0.008)  # 0.25 x 0.2 cm across
        self.assertAlmostEqual(float(np.ptp(a[:, 1])), 1.0 + 0.3, delta=0.25)  # streaked along y over its motion
        self.assertLess(float(np.std(a[:, 0])), 0.06)
        self.assertLess(float(np.abs(pts[:, 2]).max()), 1e-9)  # in the camera's plane

    def test_glints_come_in_clusters(self):
        # glints in small groups, as the reference's (foam-like): each centre a few, close round it
        centres = np.array([[10.0, 10.0, 10.0], [40.0, 40.0, 40.0]])
        pts = mv.glitter_clusters(centres, mean_count=3.0, radius=2.0, seed=0)
        self.assertGreater(len(pts), 2)
        near = np.min(np.linalg.norm(pts[:, None, :] - centres[None], axis=2), axis=1)
        self.assertLess(float(np.percentile(near, 95)), 6.0)
        np.testing.assert_array_equal(pts, mv.glitter_clusters(centres, mean_count=3.0, radius=2.0, seed=0))

    def test_dark_flecks_found(self):
        # the reference's debris: small near-black specks on its smoke
        img = np.zeros((90, 160, 3), np.uint8)
        img[...] = (60, 140, 70)
        for y, x in ((20, 30), (50, 100), (70, 40)):
            img[y:y + 2, x:x + 2] = (10, 20, 12)
        f = mv.dark_flecks(img)
        self.assertEqual(sorted((round(x), round(y)) for x, y, _ in f), [(30, 20), (40, 70), (100, 50)])

    def test_pixel_rays_invert_the_projection(self):
        cam = {"position": (1.0, 2.0, 52.0), "target": (0.0, 0.0, 0.0), "focal": 50.0}
        p = np.array([[3.0, -1.0, 5.0]])
        px, py = mv.project_points(p, cam, 800, 450)
        o, d = mv.pixel_rays(px, py, cam, 800, 450)
        to_p = (p - o) / np.linalg.norm(p - o, axis=1, keepdims=True)
        np.testing.assert_allclose(d, to_p, atol=1e-9)

    def test_surface_hit_on_the_camera_side(self):
        d = self.d  # the ball, radius ~12 round (20, 20, 20)
        hit = mv.surface_hit(d, np.array([[-100.0, 20.0, 20.0]]), np.array([[1.0, 0.0, 0.0]]), tau_scale=1.0, tau_hit=0.7)
        self.assertAlmostEqual(float(hit[0, 0]), 8.5, delta=1.5)  # its near surface (x ~ 8)
        self.assertAlmostEqual(float(hit[0, 1]), 20.0, delta=0.01)

    def test_points_project_through_the_shot_camera(self):
        # Falcor's pinhole: the focal length over a 24 mm frame height sets the vertical field of view
        cam = {"position": (0.0, 0.0, 52.0), "target": (0.0, 0.0, 0.0), "focal": 50.0}
        px, py = mv.project_points(np.array([[0.0, 0.0, 0.0], [2.0, 1.0, 0.0], [0.0, 0.0, 26.0]]), cam, 800, 450)
        k = 50.0 / 12.0 * 225.0
        np.testing.assert_allclose(px, [400.0, 400.0 + k * 2.0 / 52.0, 400.0])
        np.testing.assert_allclose(py, [225.0, 225.0 - k * 1.0 / 52.0, 225.0])

    def test_sparkle_mask_finds_the_glints(self):
        # a reference's sparkles: small bright peaks over its smoke, their density smoothed, peak 1
        img = np.zeros((90, 160, 3), np.uint8)
        img[...] = (40, 120, 50)  # green smoke (BGR)
        rng = np.random.default_rng(0)
        for y, x in zip(rng.integers(10, 40, 60), rng.integers(10, 70, 60)):  # glints in the upper left only
            img[y, x] = (150, 230, 160)
        m = mv.sparkle_mask(img, sigma=4.0)
        self.assertEqual(m.shape, (90, 160))
        self.assertAlmostEqual(float(m.max()), 1.0)
        self.assertGreater(float(m[10:40, 10:70].mean()), 20 * float(m[55:, 100:].mean() + 1e-6))

    def test_sizes_spread_lognormally_round_the_median(self):
        s = mv.glitter_sizes(4000, 0.035, 0.6, seed=2)
        self.assertEqual(len(s), 4000)
        self.assertAlmostEqual(float(np.median(s)), 0.035, delta=0.002)
        self.assertAlmostEqual(float(np.std(np.log(s))), 0.6, delta=0.03)
        self.assertEqual(s, mv.glitter_sizes(4000, 0.035, 0.6, seed=2))  # seeded
        self.assertEqual(mv.glitter_sizes(10, 0.035, 0.0), 0.035)  # no spread: one size

    def test_repeatable(self):
        a = mv.glitter_points(self.d, n=50, key=(1.0, 0.0, 0.0), threshold=0.5, seed=3)
        np.testing.assert_array_equal(a, mv.glitter_points(self.d, n=50, key=(1.0, 0.0, 0.0), threshold=0.5, seed=3))


class TestRaw(unittest.TestCase):
    def test_raw_is_x_slowest(self):
        # VolFromRaw reads data[(i * ny + j) * nz + k] as voxel (i, j, k)
        a = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "a.raw")
            mv.write_raw(a, p)
            flat = np.fromfile(p, dtype=np.float32)
        self.assertEqual(flat[(1 * 3 + 2) * 4 + 3], a[1, 2, 3])
        self.assertEqual(flat.size, 24)


if __name__ == "__main__":
    unittest.main()
