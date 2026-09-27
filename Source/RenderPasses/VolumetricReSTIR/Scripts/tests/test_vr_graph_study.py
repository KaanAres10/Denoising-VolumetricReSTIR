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
        self.assertIsInstance(params["mInitialM"], int)

    def test_mutation_knobs_absent_when_unset(self):
        params = self.restir_params()
        for key in ("mMutationCount", "mMutationStrategyMask", "mMutationStats"):
            self.assertNotIn(key, params)

    def test_mutation_knobs(self):
        os.environ.update({"VR_MUTATIONS": "5", "VR_MUT_STATS": "1"})
        for strat, mask in (("light,depth", 3), ("depth", 2), ("light", 1), ("", 0)):
            os.environ["VR_MUT_STRAT"] = strat  # set but empty = no strategy: every step a self-transition
            params = self.restir_params()
            self.assertEqual(params["mMutationStrategyMask"], mask, strat)
        self.assertEqual(params["mMutationCount"], 5)
        self.assertIsInstance(params["mMutationCount"], int)
        self.assertIs(params["mMutationStats"], True)

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
