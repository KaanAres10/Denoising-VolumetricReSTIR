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
