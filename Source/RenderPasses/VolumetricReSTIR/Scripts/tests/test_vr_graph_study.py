"""vr_graph.py's decorrelation-study additions: scene loaders, VR_PHASE_G, and the reuse knobs.

vr_graph imports `falcor`, which only exists inside Mogwai, so this stubs it and records what the
loaders and add_restir hand to Mogwai.

    python -m unittest test_vr_graph_study -v
"""
import importlib
import os
import sys
import types
import unittest

import numpy as np
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

STUDY_VARS = ("VR_PHASE_G", "VR_DENSITY_MULT", "VR_MTHRESH", "VR_SR_RADIUS", "VR_SR_COUNT", "VR_SR_ROUNDS",
              "VR_MUTATIONS", "VR_MUT_STRAT", "VR_MUT_STATS", "VR_INITIAL_M",
              "VR_DECOUPLED", "VR_DUP_CAP", "VR_MUT_AFTER_SPATIAL", "VR_TARGET_MIP", "VR_SELECT_UNIFORM",
              "VR_PARAMS", "VR_EXPLOSION_LESCALE", "VR_EXPLOSION_TSCALE", "VR_MAX_BOUNCES", "VR_MUT_COHERENT",
              "VR_MUT_EARLY_REJECT")


class Recorder:
    """Records every method call; attributes assigned on it are kept as plain attributes."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return call


def fake_falcor():
    mod = types.ModuleType("falcor")
    mod.float3 = lambda *a: tuple(a)
    mod.float2 = lambda *a: tuple(a)
    mod.createPass = lambda name, props=None: (name, props)
    mod.RenderGraph = lambda name: Recorder()
    return mod


def fresh_vr():
    sys.modules["falcor"] = fake_falcor()
    import vr_graph
    vr = importlib.reload(vr_graph)
    m = Recorder()
    m.scene = Recorder()
    m.scene.camera = types.SimpleNamespace()
    m.scene.envMap = types.SimpleNamespace()
    vr.bind(m)
    return vr, m


def volume_call(m):
    for name, _, kwargs in m.scene.calls:
        if name in ("addGVDBVolume", "addGVDBVolumeSequence"):
            return kwargs
    raise AssertionError("loader added no GVDB volume")


class StudyEnv(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.pop(k) for k in STUDY_VARS if k in os.environ}

    def tearDown(self):
        for k in STUDY_VARS:
            os.environ.pop(k, None)
        os.environ.update(self._saved)


class TestLoaders(StudyEnv):
    ALL = ("plume", "bistro", "explosion", "emerald", "bunny", "wdas")

    def test_every_study_scene_is_registered(self):
        vr, _ = fresh_vr()
        self.assertTrue(set(self.ALL).issubset(vr.SCENES), sorted(vr.SCENES))

    def test_the_fire_plume_dataset_is_not_used(self):
        # The user excluded the JangaFX EmberGen datasets from the study (2026-09-27), then asked for the dust
        # shockwave by name for film shots (2026-10-11): the fire plume stays out.
        vr, _ = fresh_vr()
        self.assertNotIn("fireplume", vr.SCENES)
        for name in vr.SCENES:
            vr, m = fresh_vr()
            vr.SCENES[name]()
            self.assertNotIn("firePlume", str(volume_call(m).get("dataFile", "")), name)

    def test_the_dust_shockwave_in_its_studio(self):
        # The user's reference (2026-10-11): a salmon dust ring in a slate studio, its shadow on the floor. Frame 50 as
        # EmberGen exported it, laid flat (the data is z-up), coloured scattering over a scalar extinction.
        vr, m = fresh_vr()
        info = vr.SCENES["duststudio"]()
        v = volume_call(m)
        self.assertTrue(v["dataFile"].endswith("dustShockwave\\dustshockwave_0050"), v["dataFile"])
        self.assertAlmostEqual(v["densityScale"], 0.3)
        self.assertEqual(v["worldRotation"], (-90, 0, 0))
        self.assertAlmostEqual(v["sigma_s"][0] + v["sigma_a"][0], 20.0)  # SceneGVDB: sigma_t = sigma_s.x + sigma_a.x
        self.assertGreater(v["sigma_s"][0], v["sigma_s"][2])  # warmer than grey
        skies = [c[1][0] for c in m.scene.calls if c[0] == "setEnvMap"]
        self.assertEqual([os.path.basename(s) for s in skies], ["studio_softbox.exr"])
        self.assertTrue(os.path.exists(skies[0]), skies[0])  # the full path, not just its name
        p = info["params"]
        self.assertEqual((p["mUseEnvironmentLights"], p["mUseAnalyticLights"], p["mUseEmissiveLights"]), (True, False, False))
        self.assertFalse(m.scene.camera.animated)
        # the reference's darker lower backdrop is the ring's shadow on a studio floor: a floor under the ring
        self.assertTrue(p["mUseSurfaceScene"])
        path = [c[1][0] for c in m.calls if c[0] == "loadScene"][0]
        self.assertTrue(path.endswith("dust_studio.pyscene"), path)
        _, meshes = TestStressScenes.run_pyscene(self, path)
        self.assertEqual(len(meshes), 1)

    def test_the_dust_shockwave_lit_by_coloured_lights(self):
        # Where the mutation count should matter (user, 2026-10-11: "add green light, have transmission, put lights in
        # different places, make the scene complex"): the studio look plus green and amber point lights inside the
        # dust (their light comes out through it), in the hole, behind the ring, and two green beams across it.
        hue = lambda c: tuple(round(v / max(c), 2) for v in c)  # noqa: E731
        vr, m = fresh_vr()
        info = vr.SCENES["dustlights"]()
        v = volume_call(m)
        self.assertTrue(v["dataFile"].endswith("dustshockwave_0050"))
        # the studio's dust unchanged (the user preferred it to a thin greenish one): the green lights carry the colour
        vs, ms = fresh_vr()
        vs.SCENES["duststudio"]()
        studio = volume_call(ms)
        self.assertEqual((v["sigma_s"], v["sigma_a"], v["densityScale"]), (studio["sigma_s"], studio["sigma_a"], studio["densityScale"]))
        skies = [c[1][0] for c in m.scene.calls if c[0] == "setEnvMap"]
        self.assertEqual([os.path.basename(s) for s in skies], ["studio_softbox.exr"])
        self.assertLess(m.scene.envMap.intensity, 1.0)  # the studio key dimmed so the coloured lights read
        p = info["params"]
        self.assertEqual((p["mUseAnalyticLights"], p["mUseEnvironmentLights"], p["mUseEmissiveLights"],
                          p["mUseSurfaceScene"]), (True, True, False, True))
        path = [c[1][0] for c in m.calls if c[0] == "loadScene"][0]
        lights, meshes = TestStressScenes.run_pyscene(self, path)
        self.assertEqual(len(meshes), 1)  # the studio floor
        self.assertEqual(len(lights), 27)
        hues = {hue(l.intensity) for l in lights}
        self.assertEqual(len(hues), 2)
        self.assertTrue(any(h[1] == 1.0 and h[0] < 0.5 for h in hues))  # green
        r = [(l.position[0] ** 2 + l.position[2] ** 2) ** 0.5 for l in lights]
        inside = [k for k, l in enumerate(lights) if 6.0 <= r[k] <= 12.0 and 0.5 <= l.position[1] <= 3.5]
        self.assertGreaterEqual(len(inside), 20)  # in the ring's body
        # the green glow at the centre (the user chose it): green lights low in the hole
        hole = [k for k in range(len(lights)) if r[k] < 3.0]
        self.assertGreaterEqual(len(hole), 2)
        self.assertTrue(all(lights[k].intensity[1] > lights[k].intensity[0] and lights[k].position[1] < 1.0 for k in hole))
        self.assertGreaterEqual(sum(1 for l in lights if l.position[2] < -14.0), 3)  # behind the ring
        self.assertEqual(sum(1 for l in lights if getattr(l, "openingAngle", 3.14) < 0.2), 2)  # the beams

    def test_the_renderman_swatch_teapot_on_fire(self):
        # The user's reference (2026-10-11): RenderMan's swatch teapot (hollow, on its stand, before the swatch's floor
        # sweep; exported from Prman_Swatch.blend) with EmberGen's fire rising from it, matched to RenderMan rendering
        # the same shot (swatch/rman_teapot_fire.py): the fire's emission and light as RenderMan's shader makes them.
        vr, m = fresh_vr()
        info = vr.SCENES["teapotfire"]()
        v = volume_call(m)
        self.assertTrue(v["dataFile"].endswith("swatch\\embergen_fire_a_67"), v["dataFile"])
        self.assertTrue(v["hasEmission"])
        self.assertEqual(v["worldRotation"], (-90, 0, 90))  # the VDB is z-up, as Blender; turned to lean right
        # RenderMan's flame: extinction = density per cm (densityScale = the voxel's cm), every voxel the 818 K LUT
        # colour (its blackbody floor's red), its red 2^10 per unit density per cm, and 8% more for its self-scattering
        self.assertEqual(v["densityScale"], 0.12)
        self.assertEqual((v["temperatureCutoff"], v["temperatureScale"]), (-818.0, 1.0))
        self.assertAlmostEqual(v["sigma_a"][0] * v["LeScale"] * vr.blackbody_lut(818.0)[0], 1.08 * 2 ** 10, places=6)
        p = info["params"]
        self.assertEqual((p["mUseAnalyticLights"], p["mUseEnvironmentLights"], p["mUseEmissiveLights"],
                          p["mUseSurfaceScene"]), (True, True, True, True))
        cam = m.scene.camera
        self.assertEqual((cam.position, cam.focalLength), ((0.0, 39.5, 150.0), 100.0))  # the .blend's RenderManCam
        path = [c[1][0] for c in m.calls if c[0] == "loadScene"][0]
        self.assertTrue(path.endswith("teapot_fire.pyscene") and os.path.exists(path), path)

        def named(n):
            r = Recorder()
            r.name = n
            return r
        builder = Recorder()
        meshes = []
        builder.addTriangleMesh = lambda mesh, material: meshes.append(material)
        env = {"sceneBuilder": builder, "PointLight": lambda n: types.SimpleNamespace(name=n), "Material": named,
               "PBRTDiffuseMaterial": named, "TriangleMesh": Recorder,
               "MaterialTextureSlot": types.SimpleNamespace(Normal="normal"),
               "float2": lambda *a: tuple(a), "float3": lambda *a: tuple(a), "float4": lambda *a: tuple(a)}
        with open(path) as fh:
            exec(fh.read(), env)
        imported = [c[1][0] for c in builder.calls if c[0] == "importScene"]
        self.assertTrue(imported and imported[0].endswith("teapot_swatch.obj") and os.path.exists(imported[0]), imported)
        swapped = [c[1][0] for c in builder.calls if c[0] == "getMaterial"]
        self.assertEqual(sorted(swapped), ["clear_glass_mat", "mesurament_mat"])  # the swatch's glass and card, replaced
        self.assertEqual(sum(1 for c in builder.calls if c[0] == "replaceMaterial"), 2)
        # the night rig's four soft boxes, emissive squares
        self.assertEqual(len(meshes), 4)
        self.assertTrue(all(mat.emissiveFactor > 0 for mat in meshes))
        lights = [c[1][0] for c in builder.calls if c[0] == "addLight"]
        self.assertTrue(lights and all(l.name.startswith("flame") for l in lights))
        self.assertTrue(all(l.intensity[0] > 0 and l.intensity[2] == 0 for l in lights))  # deep red, as RenderMan's
        # in the flames: from inside the pot (its bottom at 14 cm, the rim at 21.8) up, over the opening
        self.assertTrue(all(abs(l.position[0]) < 8 and 14 < l.position[1] < 30 and abs(l.position[2]) < 8 for l in lights))
        inside = [l for l in lights if l.position[1] < 21.8]
        above = [l for l in lights if l.position[1] >= 21.8]
        self.assertTrue(inside and above)
        self.assertAlmostEqual(inside[0].intensity[0] / above[0].intensity[0], 2.75, places=9)
        # the fire's power, as its volume emits it: 2^10 x (0.12 cm)^3 x the summed density, the lights inside 2.75x
        table = env["table"]
        total = sum(l.intensity[0] for l in above) + sum(l.intensity[0] for l in inside) / 2.75
        self.assertAlmostEqual(total / (2 ** 10 * 0.12 ** 3 * table["flames_sum"]), 1.0, places=9)

    def test_the_bifrost_fire_over_the_teapot(self):
        # the user's Maya + Bifrost (2026-10-17): Bifrost's large turbulent fire simulated headless (bifrost_export.py),
        # each frame rewritten for gImportVDB (make_volumes.py clean_bifrost_vdb), over the teapot as the EmberGen fires
        # are: its temperature already kelvin (scale 1, cutoff 0), y up as Maya is
        import swatch_fire
        g = swatch_fire.SEQUENCES["bifrostfire"]
        vr, m = fresh_vr()
        info = vr.SCENES["teapotbifrost"]()
        v = volume_call(m)
        self.assertTrue(v["dataFile"].endswith("bifrostfire%d" % g["frame"]), v["dataFile"])
        self.assertTrue(v["hasEmission"])
        self.assertEqual((v["temperatureScale"], v["temperatureCutoff"]), (1.0, 0.0))
        self.assertEqual(v["worldRotation"], (0.0, 0.0, 0.0))
        self.assertEqual(v["LeScale"], g["le_scale"] * g["glow"])
        self.assertTrue(g["src"].startswith("BifrostVDB/") and g["bifrost_src"].startswith("BifrostVDB/"))

    def test_the_other_teapot_fires_glow_and_light_as_their_tables_say(self):
        # the authored fire and the gasoline explosion (user, 2026-10-13): emissive volumes over the teapot's stage, lit
        # by point lights made from what they emit; TEAPOT_FRAME picks the explosion's frame
        import swatch_fire
        import volume_boxes
        for name, cfg in (("teapotflame", volume_boxes.TEAPOT_FIRE), ("teapotgasoline", swatch_fire.GASOLINE)):
            vr, m = fresh_vr()
            info = vr.SCENES[name]()
            v = volume_call(m)
            self.assertTrue(v["hasEmission"], name)
            # the camera sees the glow at `glow` of what the lights were made from (the sequences: 1/16, to keep detail)
            self.assertEqual((v["LeScale"], v["temperatureCutoff"]), (cfg["le_scale"] * cfg.get("glow", 1.0), cfg["cutoff"]), name)
            self.assertTrue(info["params"]["mUseEmissiveLights"] and info["params"]["mUseAnalyticLights"], name)
            path = [c[1][0] for c in m.calls if c[0] == "loadScene"][0]
            builder = Recorder()
            env = {"sceneBuilder": builder, "PointLight": lambda n: types.SimpleNamespace(name=n),
                   "Material": lambda n: Recorder(), "PBRTDiffuseMaterial": lambda n: Recorder(), "TriangleMesh": Recorder,
                   "MaterialTextureSlot": types.SimpleNamespace(Normal="normal"),
                   "float2": lambda *a: tuple(a), "float3": lambda *a: tuple(a), "float4": lambda *a: tuple(a)}
            with open(path) as fh:
                exec(fh.read(), env)
            self.assertTrue(any(c[0] == "importScene" for c in builder.calls), name)  # the stage ran first
            lights = [c[1][0] for c in builder.calls if c[0] == "addLight"]
            self.assertEqual(len(lights), cfg["lights"], name)
            total = [sum(l.intensity[c] for l in lights) for c in range(3)]
            self.assertAlmostEqual(sum(total) / sum(env["table"]["total"]), 1.0, delta=0.02)  # its emission, shared out
        os.environ["TEAPOT_FRAME"] = "55"
        try:
            vr, m = fresh_vr()
            vr.SCENES["teapotgasoline"]()
            self.assertTrue(volume_call(m)["dataFile"].endswith("gasoline55"))
        finally:
            del os.environ["TEAPOT_FRAME"]

    def test_the_green_tornadoes_stand_in_their_sky_lit_by_a_few_big_lights(self):
        # the user's Lanterns reference (2026-10-17): the looping tornado and the dust devil as green funnels, lit by a
        # few big lights (not many small ones) and the authored sky
        import lantern
        for shot in ("lantern", "lanterndust"):
            g = lantern.SHOTS[shot]
            vr, m = fresh_vr()
            info = vr.SCENES[shot]()
            v = volume_call(m)
            self.assertTrue(v["dataFile"].endswith("%s%d" % (g["data"], g["frame"])), v["dataFile"])
            self.assertFalse(v["hasEmission"])
            self.assertEqual((v["sigma_s"], v["worldRotation"]), (g["sigma_s"], g["rotation"]))
            self.assertGreater(info["scatterAlbedo"][1], info["scatterAlbedo"][0])  # green
            env = [c[1][0] for c in m.scene.calls if c[0] == "setEnvMap"]
            self.assertTrue(env and env[0].endswith(g["sky"] + ".exr"), env)
            path = [c[1][0] for c in m.calls if c[0] == "loadScene"][0]
            builder = Recorder()
            scope = {"sceneBuilder": builder, "PointLight": lambda n: types.SimpleNamespace(name=n), "float3": lambda *a: tuple(a),
                     "float2": lambda *a: tuple(a), "float4": lambda *a: tuple(a), "Material": lambda n: types.SimpleNamespace(name=n),
                     "TriangleMesh": lambda: Recorder()}
            with open(path) as fh:
                exec(fh.read(), scope)
            lights = [c[1][0] for c in builder.calls if c[0] == "addLight"]
            glow = g.get("glow", {"n": 0, "power": 0.0, "rgb": (0.0, 0.0, 0.0)})  # the tornado's are soft boxes
            self.assertEqual(len(lights), glow["n"], shot)
            self.assertAlmostEqual(sum(l.intensity[1] for l in lights), glow["power"] * glow["rgb"][1], places=6)
            self.assertEqual(info["params"]["mUseAnalyticLights"], glow["n"] > 0)  # never on with no point lights

    def test_the_looping_tornado_stands_as_its_preview_shows_it(self):
        # the user (2026-10-17): the original looping tornado, as JangaFX's preview shows it -- upright (z up -> y up,
        # turned only about its own axis), its own structure with the Lanterns construct's detail added
        # (make_volumes.py tornado_detail, not reshaped), under its own dark sky
        import lantern
        g = lantern.SHOTS["lantern"]
        vr, m = fresh_vr()
        vr.SCENES["lantern"]()
        v = volume_call(m)
        self.assertTrue(v["dataFile"].endswith("tornadodetail%d" % g["frame"]), v["dataFile"])
        self.assertEqual(v["worldRotation"][:2], (-90.0, 0.0))
        self.assertIn("detail", g)
        env = [c[1][0] for c in m.scene.calls if c[0] == "setEnvMap"]
        self.assertTrue(env[0].endswith("lantern_sky.exr"), env)  # the construct's own backdrop

    def test_a_detailed_frame_is_placed_by_its_own_grid(self):
        # make_volumes.py write_lantern writes each detailed frame on its own finer grid (its index box starts where the
        # frame's does) and records that grid's voxel, middle and density in its _lights.json: the loader takes them,
        # so every frame of the loop lands in the same place at the same optical depth
        import json
        import lantern
        g = lantern.SHOTS["lantern"]
        vr, m = fresh_vr()
        table = json.load(open(os.path.join(vr.DATA_DIR, g["data"], "%s%d_lights.json" % (g["data"], g["frame"]))))
        grid = table["grid"]  # the frame's own: where its middle is on its finer grid
        up = g["detail"]["up"]
        vr.SCENES["lantern"]()
        v = volume_call(m)
        self.assertAlmostEqual(v["worldScaling"], g["scale"] / up)  # the voxel and density 1 / up as large: lantern.py's
        self.assertAlmostEqual(v["densityScale"], g["density_scale"] / up)
        import swatch_fire
        expect = swatch_fire.translation(**dict(lantern.pose("lantern"), scale=g["scale"] / up, base=grid["base"]))
        np.testing.assert_allclose(v["worldTranslation"], expect, atol=1e-9)

    def test_the_looping_tornado_is_lit_by_big_soft_boxes_out_of_shot(self):
        # the user (2026-10-17): complicated enough that mutations are useful, with big lights -- large emissive soft
        # boxes, each its own tint (a pixel's sample carries its light's colour), facing the funnel, none in shot
        import lantern
        g = lantern.SHOTS["lantern"]
        vr, m = fresh_vr()
        info = vr.SCENES["lantern"]()
        self.assertTrue(info["params"]["mUseEmissiveLights"] and info["params"]["mUseSurfaceScene"])

        class Mesh:
            def __init__(self):
                self.v, self.t = [], []

            def addVertex(self, p, n, uv):
                self.v.append(np.array(p, float))

            def addTriangle(self, a, b, c):
                self.t.append((a, b, c))

        path = [c[1][0] for c in m.calls if c[0] == "loadScene"][0]
        builder = Recorder()
        scope = {"sceneBuilder": builder, "PointLight": lambda n: types.SimpleNamespace(name=n),
                 "Material": lambda n: types.SimpleNamespace(name=n), "TriangleMesh": Mesh,
                 "float2": lambda *a: tuple(a), "float3": lambda *a: tuple(a), "float4": lambda *a: tuple(a)}
        with open(path) as fh:
            exec(fh.read(), scope)
        boxes = [c[1] for c in builder.calls if c[0] == "addTriangleMesh"]
        self.assertEqual(len(boxes), len(g["panels"]))
        self.assertEqual(len({tuple(mat.emissiveColor) for _, mat in boxes}), len(boxes))  # each its own tint
        cam = g["camera"]
        eye, target = np.array(cam["position"], float), np.array(cam["target"], float)
        fwd = (target - eye) / np.linalg.norm(target - eye)
        right = np.cross(fwd, (0.0, 1.0, 0.0))
        right /= np.linalg.norm(right)
        up = np.cross(right, fwd)
        tan_v = 12.0 / cam["focal"]  # Falcor's frame: 24 mm high
        for mesh, mat in boxes:
            self.assertGreater(mat.emissiveFactor, 0.0)
            q = [p - eye for p in mesh.v]
            x = [np.dot(p, right) / np.dot(p, fwd) / (tan_v * 16 / 9) for p in q]
            y = [np.dot(p, up) / np.dot(p, fwd) / tan_v for p in q]
            self.assertTrue(all(np.dot(p, fwd) > 0 for p in q))
            self.assertTrue(min(x) > 1 or max(x) < -1 or min(y) > 1 or max(y) < -1, (x, y))  # wholly out of shot
            centre = sum(mesh.v) / len(mesh.v)
            for a, b, c in mesh.t:  # wound to emit toward the funnel
                n = np.cross(mesh.v[b] - mesh.v[a], mesh.v[c] - mesh.v[a])
                self.assertGreater(np.dot(n, target - centre), 0.0)

    def test_blackbody_lut_reads_as_the_shader_samples_it(self):
        # VolumeBase.slang ConvertTempToColor: a 128-texel 1D texture, linear filtering, texel i at 50 + 50 i kelvin
        vr, _ = fresh_vr()
        self.assertEqual(vr.blackbody_lut(800.0), (7.7e-05, 1e-06, 0.0))  # row 15, as the file has it
        r, g, b = vr.blackbody_lut(818.0)  # 36% of the way to row 16 (3.03e-4, 2e-6, 0)
        self.assertAlmostEqual(r, 7.7e-05 + 0.36 * (3.03e-04 - 7.7e-05), places=12)
        self.assertAlmostEqual(g, 1e-06 + 0.36 * 1e-06, places=12)
        self.assertEqual(b, 0.0)

    def test_loaders_return_the_graph_settings(self):
        for name in self.ALL:
            vr, _ = fresh_vr()
            info = vr.SCENES[name]()
            for key in ("scatterAlbedo", "exposure", "params"):
                self.assertIn(key, info, name)

    def test_phase_g_is_unchanged_when_unset(self):
        for name in self.ALL:
            vr, m = fresh_vr()
            vr.SCENES[name]()
            self.assertEqual(volume_call(m)["g"], 0.0, name)

    def test_phase_g_override_reaches_every_loader(self):
        os.environ["VR_PHASE_G"] = "-0.9"
        for name in self.ALL:
            vr, m = fresh_vr()
            vr.SCENES[name]()
            self.assertAlmostEqual(volume_call(m)["g"], -0.9, msg=name)

    def test_density_multiplier_scales_the_medium(self):
        # Lin et al. 2021's WDAS figure: 0.2x / 1x / 3x density. Unset keeps each scene's own density.
        defaults = {}
        for name in self.ALL:
            vr, m = fresh_vr()
            vr.SCENES[name]()
            defaults[name] = volume_call(m).get("densityScale")
        self.assertEqual(defaults["wdas"], 0.03)
        os.environ["VR_DENSITY_MULT"] = "0.2"
        for name in self.ALL:
            vr, m = fresh_vr()
            vr.SCENES[name]()
            expected = (defaults[name] if defaults[name] is not None else 1.0) * 0.2
            self.assertAlmostEqual(volume_call(m)["densityScale"], expected, msg=name)

    def test_env_map_uses_falcor9_properties(self):
        # Falcor 9's Scene has no setEnvMapRotation / setEnvMapIntensity (the 4.x run scripts used them);
        # rotation and intensity are properties of scene.envMap.
        expected = {"emerald": ((0, 72.5, 0), 0.003), "wdas": ((-37.5, 93.5, 27), 1.1)}
        for name in self.ALL:
            vr, m = fresh_vr()
            vr.SCENES[name]()
            called = {c[0] for c in m.scene.calls}
            self.assertFalse(called & {"setEnvMapRotation", "setEnvMapIntensity"}, name)
            if name in expected:
                rotation, intensity = expected[name]
                self.assertEqual(m.scene.envMap.rotation, rotation, name)
                self.assertEqual(m.scene.envMap.intensity, intensity, name)

    def test_display_exposure_matches_the_original_run_scripts(self):
        # ToneMapper exposureCompensation from run_emerald_square.py (+8.5: a dusk scene under a 0.003 env
        # map) and run_bistro.py (+8); at 0 the window shows emerald nearly black. Display only: the study
        # captures the HDR accumulated_color, before the tonemapper.
        for name, ev in (("emerald", 8.5), ("bistro", 8.0)):
            vr, _ = fresh_vr()
            self.assertEqual(vr.SCENES[name]()["exposure"], ev, name)

    def test_new_loaders_pin_the_camera(self):
        for name in ("emerald", "bunny", "wdas"):
            vr, m = fresh_vr()
            vr.SCENES[name]()
            cam = m.scene.camera
            self.assertFalse(cam.animated, name)
            for attr in ("position", "target", "up"):
                self.assertTrue(hasattr(cam, attr), (name, attr))


class TestStressScenes(StudyEnv):
    """Scenes built to provoke volumetric ReSTIR's artifacts (spec V-B9): the bunny cloud under three coloured
    point lights, one white light in front, one behind; the heterogeneous plume under one light."""
    LIGHTS = {"bunnyrgb": 3, "bunnyone": 1, "bunnyback": 1, "plumeone": 1,
              "bunnyinside": 1, "bunnyspot": 1, "bunnyparty": 8, "plumeback": 1}

    def test_registered_under_names_run_study_can_parse(self):
        vr, _ = fresh_vr()
        for name in self.LIGHTS:
            self.assertIn(name, vr.SCENES)
            self.assertNotIn("_", name)  # run_study.sh reads _g<g> / _d<mult> suffixes off the label

    def test_lit_by_their_point_lights_only(self):
        for name, count in self.LIGHTS.items():
            vr, m = fresh_vr()
            p = vr.SCENES[name]()["params"]
            self.assertEqual((p["mUseAnalyticLights"], p["mUseEnvironmentLights"], p["mUseEmissiveLights"]),
                             (True, False, False), name)
            path = [c[1][0] for c in m.calls if c[0] == "loadScene"][0]
            self.assertTrue(path.endswith(".pyscene") and os.path.exists(path), path)
            # Run the .pyscene against a stand-in scene builder and count the lights it adds.
            builder = Recorder()
            with open(path) as fh:
                exec(fh.read(), {"sceneBuilder": builder, "PointLight": lambda n: types.SimpleNamespace(name=n),
                                 "float3": lambda *a: tuple(a)})
            lights = [c[1][0] for c in builder.calls if c[0] == "addLight"]
            self.assertEqual(len(lights), count, name)
            self.assertTrue(all(len(l.intensity) == 3 and len(l.position) == 3 for l in lights), name)

    def run_pyscene(self, path):
        """Runs a .pyscene against a stand-in scene builder: (lights, mesh instances with their materials)."""
        builder = Recorder()
        env = {"sceneBuilder": builder, "PointLight": lambda n: types.SimpleNamespace(name=n),
               "Material": lambda n: types.SimpleNamespace(name=n), "Transform": lambda **k: k,
               "PBRTDiffuseMaterial": lambda n: types.SimpleNamespace(name=n),
               "TriangleMesh": types.SimpleNamespace(createCube=lambda *a, **k: "cube", createQuad=lambda *a, **k: "quad",
                                                     createSphere=lambda *a, **k: "sphere"),
               "float3": lambda *a: tuple(a), "float4": lambda *a: tuple(a)}
        with open(path) as fh:
            exec(fh.read(), env)
        lights = [c[1][0] for c in builder.calls if c[0] == "addLight"]
        meshes = [c[1] for c in builder.calls if c[0] == "addTriangleMesh"]
        return lights, meshes

    def test_new_scenes(self):
        # (name, lights, occluder or emitter meshes, (analytic, env, emissive, surfaces))
        for name, n_lights, n_meshes, flags in (("bunnyslabs", 1, 9, (True, False, False, True)),
                                                ("bunnystripes", 1, 9, (True, False, False, True)),
                                                ("bunnysoftbox", 0, 2, (False, False, True, True)),
                                                ("bunnylanterns", 48, 0, (True, False, False, False))):
            vr, m = fresh_vr()
            self.assertNotIn("_", name)
            p = vr.SCENES[name]()["params"]
            self.assertEqual((p["mUseAnalyticLights"], p["mUseEnvironmentLights"], p["mUseEmissiveLights"],
                              p.get("mUseSurfaceScene", False)), flags, name)
            path = [c[1][0] for c in m.calls if c[0] == "loadScene"][0]
            lights, meshes = self.run_pyscene(path)
            self.assertEqual(len(lights), n_lights, name)
            self.assertEqual(len(meshes), n_meshes, name)
        # Mutation-count scenes (spec V-C7): where one mutation per frame should not be enough.
        for name, n_lights, n_meshes, flags in (("bunnyswarm", 192, 0, (True, False, False, False)),
                                                ("bunnybeam", 1, 0, (True, False, False, False)),
                                                ("bunnypinback", 1, 0, (True, False, False, False)),
                                                ("bunnyclosebox", 0, 2, (False, False, True, True))):
            vr, m = fresh_vr()
            self.assertNotIn("_", name)
            p = vr.SCENES[name]()["params"]
            self.assertEqual((p["mUseAnalyticLights"], p["mUseEnvironmentLights"], p["mUseEmissiveLights"],
                              p.get("mUseSurfaceScene", False)), flags, name)
            path = [c[1][0] for c in m.calls if c[0] == "loadScene"][0]
            lights, meshes = self.run_pyscene(path)
            self.assertEqual((len(lights), len(meshes)), (n_lights, n_meshes), name)
            if name == "bunnyswarm":  # neighbouring lights must not share a hue family, or their colours would not clump
                hues = {tuple(round(c / max(l.intensity), 2) for c in l.intensity) for l in lights}
                self.assertEqual(len(hues), 6)
            if name == "bunnybeam":  # far narrower than bunnyspot's 0.12 rad
                self.assertLess(lights[0].openingAngle, 0.03)
        # A concert lighting rig in stage haze (spec V-C7): many coloured fixtures, where the count matters.
        vr, m = fresh_vr()
        p = vr.SCENES["plumerig"]()["params"]
        self.assertEqual((p["mUseAnalyticLights"], p["mUseEnvironmentLights"], p["mUseEmissiveLights"]), (True, False, False))
        lights, meshes = self.run_pyscene([c[1][0] for c in m.calls if c[0] == "loadScene"][0])
        self.assertEqual((len(lights), len(meshes)), (46, 0))
        beams = [l for l in lights if getattr(l, "openingAngle", 3.14) < 0.2]
        self.assertEqual(len(beams), 6)
        families = {tuple(round(c / max(l.intensity), 2) for c in l.intensity) for l in lights}
        self.assertGreaterEqual(len(families), 6)
        # More real-world shots (spec V-C7): an LED video wall behind the haze, a night thunderstorm over a city,
        # a neon street in fog.
        for name, n_lights, n_meshes, flags in (("plumewall", 0, 32, (False, False, True, True)),
                                                ("wdasstorm", 36, 0, (True, False, False, False)),
                                                ("emeraldneon", 40, 0, (True, True, True, True))):
            vr, m = fresh_vr()
            self.assertNotIn("_", name)
            p = vr.SCENES[name]()["params"]
            self.assertEqual((p["mUseAnalyticLights"], p["mUseEnvironmentLights"], p["mUseEmissiveLights"],
                              p.get("mUseSurfaceScene", False)), flags, name)
            path = [c[1][0] for c in m.calls if c[0] == "loadScene"][0]
            self.assertTrue(path.endswith(".pyscene"), name)
            lights, meshes = self.run_pyscene(path)
            self.assertEqual((len(lights), len(meshes)), (n_lights, n_meshes), name)
            if name == "wdasstorm":  # a night scene: no sky
                self.assertFalse([c for c in m.scene.calls if c[0] == "setEnvMap"], name)
        # Film-style shots (spec V-B10): concert beams through stage smoke, god rays in a stone room.
        for name, n_lights, n_meshes, flags in (("plumeconcert", 6, 0, (True, False, False, False)),
                                                ("bunnycathedral", 1, 11, (True, False, False, True))):
            vr, m = fresh_vr()
            p = vr.SCENES[name]()["params"]
            self.assertEqual((p["mUseAnalyticLights"], p["mUseEnvironmentLights"], p["mUseEmissiveLights"],
                              p.get("mUseSurfaceScene", False)), flags, name)
            path = [c[1][0] for c in m.calls if c[0] == "loadScene"][0]
            lights, meshes = self.run_pyscene(path)
            self.assertEqual((len(lights), len(meshes)), (n_lights, n_meshes), name)
        lights, _ = self.run_pyscene(vr.SCENE_DIR + r"\plume_concert.pyscene")
        self.assertTrue(all(0.0 < l.openingAngle < 0.2 for l in lights))  # narrow beams
        self.assertEqual(len({tuple(round(c / max(l.intensity), 2) for c in l.intensity) for l in lights}), 6)
        # The sunset: the Disney cloud with the dawn sun yawed behind it; the night street: Emerald's fog, lamps only.
        vr, m = fresh_vr()
        vr.SCENES["wdassunset"]()
        self.assertEqual(m.scene.envMap.rotation, (0, 165, 0))
        vr, m = fresh_vr()
        info = vr.SCENES["emeraldnight"]()
        self.assertLess(m.scene.envMap.intensity, 0.003)
        self.assertTrue(info["params"]["mUseEmissiveLights"])
        # The softbox panels glow in two different colours.
        _, meshes = self.run_pyscene(vr.SCENE_DIR + r"\bunny_softbox.pyscene")
        colours = {tuple(mat.emissiveColor) for _, mat in meshes}
        self.assertEqual(len(colours), 2)

    def test_pleasant_shots(self):
        # Film shots with a real backdrop and a restrained palette (user, 2026-10-11: "more aesthetically pleasant
        # scenes"), each still lit from inside or through the medium so the mutation count matters:
        # (name, lights, meshes, (analytic, env, emissive, surfaces), sky map or None, light colours)
        hue = lambda c: tuple(round(v / max(c), 2) for v in c)  # noqa: E731
        for name, n_lights, n_meshes, flags, sky, n_hues in (
                ("wdasdusk", 5, 0, (True, True, False, False), "kiara_1_dawn_8k.hdr", 1),
                ("lanterns", 0, 36, (False, True, True, True), "satara_night_8k.hdr", 1),
                ("fireworks", 40, 150, (True, True, True, True), "hansaplatz_8k.hdr", 3),
                ("stage", 14, 15, (True, False, False, True), None, 2)):
            vr, m = fresh_vr()
            self.assertNotIn("_", name)
            info = vr.SCENES[name]()
            p = info["params"]
            self.assertEqual((p["mUseAnalyticLights"], p["mUseEnvironmentLights"], p["mUseEmissiveLights"],
                              p.get("mUseSurfaceScene", False)), flags, name)
            skies = [c[1][0] for c in m.scene.calls if c[0] == "setEnvMap"]
            self.assertEqual([os.path.basename(s) for s in skies], [sky] if sky else [], name)
            self.assertFalse(m.scene.camera.animated, name)
            path = [c[1][0] for c in m.calls if c[0] == "loadScene"][0]
            self.assertTrue(path.endswith(".pyscene") and os.path.exists(path), name)
            lights, meshes = self.run_pyscene(path)
            self.assertEqual((len(lights), len(meshes)), (n_lights, n_meshes), name)
            colours = {hue(l.intensity) for l in lights} | {hue(mat.emissiveColor) for _, mat in meshes
                                                             if hasattr(mat, "emissiveColor")}
            self.assertEqual(len(colours), n_hues, (name, colours))
        # Three of them in volumes authored for them (make_volumes.py), placed at their box's min corner.
        import volume_boxes as vb
        for name, volume in (("stage", "stagehaze"), ("lanterns", "groundmist"), ("fireworks", "smokepuffs")):
            vr, m = fresh_vr()
            vr.SCENES[name]()
            v = volume_call(m)
            self.assertTrue(v["dataFile"].endswith("authored\\" + volume), (name, v["dataFile"]))
            self.assertEqual((v["worldTranslation"], v["worldScaling"]), (vb.BOXES[volume][0], 1.0), name)
        # The stage's ten truss beams are narrow spots.
        lights, _ = self.run_pyscene(vr.SCENE_DIR + r"\stage.pyscene")
        self.assertEqual(sum(1 for l in lights if l.openingAngle < 0.15), 10)
        # The firework sparks sit on the bursts the smoke was built around.
        lights, _ = self.run_pyscene(vr.SCENE_DIR + r"\fireworks.pyscene")
        for c, radius in vb.BURSTS:
            near = [l for l in lights if sum((a - b) ** 2 for a, b in zip(l.position, c)) ** 0.5 <= radius + 1e-6]
            self.assertEqual(len(near), 8, c)

    def test_falcor4_env_rotation(self):
        # Falcor 4 applied Rz Ry Rx; Falcor 9's envMap.rotation applies Rx Ry Rz. A single-axis rotation
        # carries over as is; the paper's explosion sky (13, 136, 340) does not.
        import math

        def rot(axis, deg):
            c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
            return {"x": [[1, 0, 0], [0, c, -s], [0, s, c]], "y": [[c, 0, s], [0, 1, 0], [-s, 0, c]],
                    "z": [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis]

        def mul(*ms):
            out = [[float(i == j) for j in range(3)] for i in range(3)]
            for b in ms:
                out = [[sum(out[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
            return out

        vr, _ = fresh_vr()
        self.assertEqual(tuple(round(v, 6) + 0.0 for v in vr.falcor4_env_rotation((0, 165, 0))), (0, 165, 0))
        for deg in ((13, 136, 340), (-37.5, 93.5, 27), (80, -20, 45)):
            x, y, z = deg
            a, b, c = vr.falcor4_env_rotation(deg)
            want, got = mul(rot("z", z), rot("y", y), rot("x", x)), mul(rot("x", a), rot("y", b), rot("z", c))
            for i in range(3):
                for j in range(3):
                    self.assertAlmostEqual(got[i][j], want[i][j], places=9, msg=str(deg))

    def test_explosiondusk_is_the_papers_look(self):
        # The paper's sky (skylight-dusk.exr, its rotation converted) and a temperature scale that keeps the
        # fire in the blackbody table's orange rows; the volume is otherwise the explosion's.
        vr, m = fresh_vr()
        vr.SCENES["explosion"]()
        base = volume_call(m)
        vr, m = fresh_vr()
        vr.SCENES["explosiondusk"]()
        vol = volume_call(m)
        env = [c[1][0] for c in m.scene.calls if c[0] == "setEnvMap"]
        self.assertTrue(env and env[-1].endswith("skylight-dusk.exr"))
        self.assertEqual(m.scene.envMap.rotation, vr.falcor4_env_rotation((13, 136, 340)))
        # run_LGHExplosion.py's own values: rendered side by side with the legacy build, the port matches it
        # at these (the "750 renders no fire" note predates the current loader).
        self.assertEqual((vol["temperatureScale"], vol["LeScale"]), (750.0, 1.0))
        self.assertEqual(m.scene.camera.up, (-0.000909, 1.0, 0.00003))
        tuned = ("temperatureScale", "LeScale")
        self.assertEqual({k: v for k, v in vol.items() if k not in tuned}, {k: v for k, v in base.items() if k not in tuned})
        os.environ["VR_EXPLOSION_LESCALE"] = "0"  # the knob still overrides
        vr, m = fresh_vr()
        vr.SCENES["explosiondusk"]()
        self.assertEqual(volume_call(m)["LeScale"], 0.0)

    def test_knobs_reach_the_stress_scenes(self):
        os.environ.update({"VR_PHASE_G": "0.8", "VR_DENSITY_MULT": "5"})
        for name in self.LIGHTS:
            vr, m = fresh_vr()
            info = vr.SCENES[name]()
            v = volume_call(m)
            self.assertAlmostEqual(v["g"], 0.8, msg=name)
            self.assertIn("densityScale", v, name)
            self.assertFalse(m.scene.camera.animated, name)
            for key in ("scatterAlbedo", "exposure", "params"):
                self.assertIn(key, info, name)


class TestKnobs(StudyEnv):
    def restir_params(self):
        vr, _ = fresh_vr()
        graph = Recorder()
        vr.add_restir(graph, {"params": {}})
        (name, args, _), = [c for c in graph.calls if c[0] == "addPass"]
        return args[0][1]["mParams"]

    def test_knobs_absent_when_unset(self):
        params = self.restir_params()
        for key in ("mTemporalReuseMThreshold", "mSampleRadius", "mSpatialSampleCount", "mSpatialReuseRounds", "mInitialM"):
            self.assertNotIn(key, params)

    def test_knobs_applied_with_their_types(self):
        os.environ.update({"VR_MTHRESH": "50", "VR_SR_RADIUS": "30", "VR_SR_COUNT": "6", "VR_SR_ROUNDS": "3",
                           "VR_INITIAL_M": "8"})
        params = self.restir_params()
        self.assertEqual(params["mTemporalReuseMThreshold"], 50.0)
        self.assertIsInstance(params["mTemporalReuseMThreshold"], float)
        self.assertEqual(params["mSampleRadius"], 30.0)
        self.assertEqual(params["mSpatialSampleCount"], 6)
        self.assertIsInstance(params["mSpatialSampleCount"], int)
        self.assertEqual(params["mSpatialReuseRounds"], 3)
        self.assertEqual(params["mInitialM"], 8)  # initial candidates: the equal-time rival of mutations
        self.assertNotIn("mSpatialLightingMipLevel", params)
        os.environ["VR_TARGET_MIP"] = "3"  # a cheaper, coarser target: both of p_hat's transmittances on mip 3
        params = self.restir_params()
        self.assertEqual((params["mSpatialLightingMipLevel"], params["mSpatialVisibilityMipLevel"]), (3, 3))
        self.assertIsInstance(params["mInitialM"], int)

    def test_mutation_knobs_absent_when_unset(self):
        params = self.restir_params()
        for key in ("mMutationCount", "mMutationStrategyMask", "mMutationStats"):
            self.assertNotIn(key, params)

    def test_mutation_knobs(self):
        os.environ.update({"VR_MUTATIONS": "5", "VR_MUT_STATS": "1"})
        for strat, mask in (("light,depth", 3), ("depth", 2), ("light", 1), ("select", 4), ("light,depth,select", 7), ("flight", 8), ("depth,flight", 10), ("", 0)):
            os.environ["VR_MUT_STRAT"] = strat  # set but empty = no strategy: every step a self-transition
            params = self.restir_params()
            self.assertEqual(params["mMutationStrategyMask"], mask, strat)
        self.assertEqual(params["mMutationCount"], 5)
        self.assertIsInstance(params["mMutationCount"], int)
        self.assertIs(params["mMutationStats"], True)
        self.assertNotIn("mMutateAfterSpatial", params)
        os.environ["VR_MUT_AFTER_SPATIAL"] = "1"  # mutate spatial reuse's output instead of the temporal one
        self.assertIs(self.restir_params()["mMutateAfterSpatial"], True)
        self.assertNotIn("mMutationSelectWeighted", self.restir_params())  # the pass's default: weighted
        os.environ["VR_SELECT_UNIFORM"] = "1"  # the re-selection's original uniform point-light proposal
        self.assertIs(self.restir_params()["mMutationSelectWeighted"], False)
        self.assertNotIn("mMutationCoherentMoves", self.restir_params())  # the pass's default: one kind per step, frame-wide
        os.environ["VR_MUT_COHERENT"] = "1"  # one move kind per step for the whole frame (no warp divergence)
        self.assertIs(self.restir_params()["mMutationCoherentMoves"], True)
        os.environ["VR_MUT_COHERENT"] = "0"  # a move kind per pixel, as before 2af014f (studies begun that way)
        self.assertIs(self.restir_params()["mMutationCoherentMoves"], False)
        self.assertNotIn("mMutationEarlyReject", self.restir_params())  # the pass's default: on
        os.environ["VR_MUT_EARLY_REJECT"] = "0"  # every proposal's shadow march to the end (the A/B baseline)
        self.assertIs(self.restir_params()["mMutationEarlyReject"], False)

    def test_bounce_knob(self):
        self.assertNotIn("mMaxBounces", self.restir_params())
        os.environ["VR_MAX_BOUNCES"] = "2"  # the paper's explosion renders 2 bounces
        params = self.restir_params()
        self.assertEqual(params["mMaxBounces"], 2)
        self.assertIsInstance(params["mMaxBounces"], int)

    def test_two_bounce_strategy_names(self):
        os.environ["VR_MUT_STRAT"] = "direction,distance,rebounce"  # MutateSamples.cs.slang bits 4-6
        self.assertEqual(self.restir_params()["mMutationStrategyMask"], 16 | 32 | 64)
        os.environ["VR_MUT_STRAT"] = "light,depth,select,flight,direction,distance,rebounce"
        self.assertEqual(self.restir_params()["mMutationStrategyMask"], 127)

    def test_sharing_knobs(self):
        params = self.restir_params()
        self.assertNotIn("mDecoupledHistory", params)
        self.assertNotIn("mDuplicationCapStrength", params)
        os.environ.update({"VR_DECOUPLED": "1", "VR_DUP_CAP": "0.5"})
        params = self.restir_params()
        self.assertIs(params["mDecoupledHistory"], True)
        self.assertEqual(params["mDuplicationCapStrength"], 0.5)
        self.assertIsInstance(params["mDuplicationCapStrength"], float)

    def test_unknown_mutation_strategy_is_an_error(self):
        os.environ["VR_MUT_STRAT"] = "light,scatter"
        with self.assertRaises(ValueError):
            self.restir_params()

    def test_params_json_is_merged_last(self):
        # Diagnostics: any mParams field, e.g. the temporal MIS method, without a dedicated knob.
        os.environ["VR_PARAMS"] = '{"mTemporalMISMethod": 0, "mTemporalReprojectionMode": 1}'
        os.environ["VR_MTHRESH"] = "50"
        params = self.restir_params()
        self.assertEqual(params["mTemporalMISMethod"], 0)
        self.assertEqual(params["mTemporalReprojectionMode"], 1)
        self.assertEqual(params["mTemporalReuseMThreshold"], 50.0)

    def test_knob_overrides_the_scene_default(self):
        os.environ["VR_MTHRESH"] = "200"
        vr, _ = fresh_vr()
        graph = Recorder()
        vr.add_restir(graph, {"params": {"mTemporalReuseMThreshold": 10.0}})
        (name, args, _), = [c for c in graph.calls if c[0] == "addPass"]
        self.assertEqual(args[0][1]["mParams"]["mTemporalReuseMThreshold"], 200.0)


if __name__ == "__main__":
    unittest.main()
