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
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

STUDY_VARS = ("VR_PHASE_G", "VR_DENSITY_MULT", "VR_MTHRESH", "VR_SR_RADIUS", "VR_SR_COUNT", "VR_SR_ROUNDS",
              "VR_MUTATIONS", "VR_MUT_STRAT", "VR_MUT_STATS", "VR_INITIAL_M",
              "VR_DECOUPLED", "VR_DUP_CAP", "VR_MUT_AFTER_SPATIAL", "VR_TARGET_MIP", "VR_SELECT_UNIFORM",
              "VR_PARAMS")


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

    def test_embergen_datasets_are_not_used(self):
        # The user excluded the JangaFX EmberGen datasets (FirePlumeVDB, DustShockwaveVDB) from the study.
        vr, _ = fresh_vr()
        self.assertFalse({"fireplume", "dust"} & set(vr.SCENES), sorted(vr.SCENES))

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
               "TriangleMesh": types.SimpleNamespace(createCube=lambda *a, **k: "cube", createQuad=lambda *a, **k: "quad"),
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
