"""denoiser_set.py: several denoisers on the same frames in one render graph (paper spec E1).

vr_graph imports `falcor`, which exists only inside Mogwai. This stubs it with a graph that keeps passes by name
(refusing a duplicate name, as Falcor does), their properties, the edges and the marked outputs.

    cd Source/RenderPasses/VolumetricReSTIR/Scripts && python -m unittest tests.test_denoiser_set -v
"""
import importlib
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

# run_study.sh's LOOK: the configuration every denoised run of the study uses.
LOOK = {"VR_NRD_SPLIT": "1", "VR_NRD_SH": "1", "VR_NRD_TAA": "1", "VR_TAA_LDR": "1", "VR_NRD_EMISSION": "1",
        "VR_NRD_VOLMASK": "1", "VR_VOL_NORMAL": "gradient"}
SCENE = {"scatterAlbedo": (0.9, 0.9, 0.9)}
RENDER = (64, 32)
COLOR = "VolumetricReSTIR.accumulated_color"


class FakePass:
    def __init__(self, kind, props):
        self.kind = kind
        self.properties = dict(props or {})

    def set_properties(self, props):
        self.properties.update(props)


class FakeGraph:
    def __init__(self):
        self.passes, self.edges, self.outputs = {}, [], []

    def addPass(self, render_pass, name):
        if name in self.passes:
            raise ValueError("duplicate pass name " + name)
        kind, props = render_pass
        self.passes[name] = FakePass(kind, props)

    def addEdge(self, src, dst):
        self.edges.append((src, dst))

    def markOutput(self, channel):
        self.outputs.append(channel)

    def get_pass(self, name):
        return self.passes[name]

    def wiring(self):
        return {n: (p.kind, p.properties) for n, p in self.passes.items()}, list(self.edges)


def modules():
    falcor = types.ModuleType("falcor")
    falcor.float3 = lambda *a: tuple(a)
    falcor.float2 = lambda *a: tuple(a)
    falcor.createPass = lambda name, props=None: (name, props)
    sys.modules["falcor"] = falcor
    import vr_graph
    import denoiser_set
    return importlib.reload(vr_graph), importlib.reload(denoiser_set)


def estimator_graph():
    g = FakeGraph()
    g.addPass(("VolumetricReSTIR", {"mMotionVecMode": "Deterministic", "mOutputDepth": True}), "VolumetricReSTIR")
    return g


class TestAddDenoisers(unittest.TestCase):
    def setUp(self):
        self.vr, self.ds = modules()
        patcher = mock.patch.dict(os.environ, LOOK)
        patcher.start()
        self.addCleanup(patcher.stop)

    def four(self):
        g = estimator_graph()
        return g, self.ds.add_denoisers(g, list(self.ds.MODES), COLOR, SCENE, RENDER)

    def test_each_denoiser_gets_its_own_prefixed_passes(self):
        g, _ = self.four()
        for name in g.passes:
            if name != "VolumetricReSTIR":
                self.assertTrue(any(name.startswith("D_%s_" % m) for m in self.ds.MODES), name)

    def test_returns_each_denoisers_output(self):
        _, channels = self.four()
        self.assertEqual(channels, {"optix": "D_optix_Denoiser.output", "oidn": "D_oidn_Denoiser.dst",
                                    "relax": "D_relax_ModulateIllumination.output",
                                    "reblur": "D_reblur_ModulateIllumination.output"})

    def test_every_edge_joins_passes_that_exist_and_the_estimator_keeps_its_name(self):
        g, _ = self.four()
        for src, dst in g.edges:
            for end in (src, dst):
                self.assertIn(end.partition(".")[0], g.passes, end)
        self.assertIn((COLOR, "D_oidn_Denoiser.src"), g.edges)

    def test_each_nrd_instance_runs_its_own_method(self):
        with mock.patch.dict(os.environ, {"VR_NRD_METHOD": "ReblurDiffuse"}):
            g, _ = self.four()
            self.assertEqual(os.environ["VR_NRD_METHOD"], "ReblurDiffuse")  # restored after each call
        for half in ("NRDSurface", "NRDVolume"):
            self.assertEqual(g.passes["D_relax_" + half].properties["method"], "RelaxDiffuseSh")
            self.assertEqual(g.passes["D_reblur_" + half].properties["method"], "ReblurDiffuseSh")
        # REBLUR packs SH0 as YCoCg and RELAX as linear RGB (vr_graph.add_nrd_split): each adapter follows its own.
        self.assertFalse(g.passes["D_relax_NRDAdapterSurface"].properties["shYCoCg"])
        self.assertTrue(g.passes["D_reblur_NRDAdapterSurface"].properties["shYCoCg"])

    def test_every_gbuffer_in_the_shared_graph_is_unjittered(self):
        # A jittering G-buffer moves the camera for every pass, the estimator included (Review Focus 1).
        g, _ = self.four()
        gbuffers = [p for p in g.passes.values() if p.kind == "GBufferRaster"]
        self.assertGreaterEqual(len(gbuffers), 4)
        for p in gbuffers:
            self.assertEqual(p.properties["samplePattern"], "Center")

    def test_an_empty_prefix_wires_exactly_as_add_denoiser(self):
        for kind, method in (("optix", None), ("nrd", "RelaxDiffuseSh"), ("nrd", "ReblurDiffuseSh")):
            values = {"VR_NRD_METHOD": method} if method else {}
            with mock.patch.dict(os.environ, values):
                direct = estimator_graph()
                self.vr.add_denoiser(direct, kind, COLOR, SCENE, RENDER, RENDER, gbuffer=None, guides=True)
            wrapped = estimator_graph()
            with self.ds.env_override(values):
                self.vr.add_denoiser(self.ds.PrefixedGraph(wrapped, ""), kind, COLOR, SCENE, RENDER, RENDER,
                                     gbuffer=None, guides=True)
            self.assertEqual(wrapped.wiring(), direct.wiring(), (kind, method))

    def test_rr_is_refused(self):
        with self.assertRaisesRegex(ValueError, "jitter"):
            self.ds.add_denoisers(estimator_graph(), ["rr"], COLOR, SCENE, RENDER)

    def test_unknown_or_repeated_denoisers_are_refused(self):
        with self.assertRaises(ValueError):
            self.ds.add_denoisers(estimator_graph(), ["svgf"], COLOR, SCENE, RENDER)
        with self.assertRaises(ValueError):
            self.ds.add_denoisers(estimator_graph(), ["optix", "optix"], COLOR, SCENE, RENDER)


class TestEnvOverride(unittest.TestCase):
    def test_restores_the_environment_when_the_block_raises(self):
        _, ds = modules()
        with mock.patch.dict(os.environ, {"VR_A": "1"}):
            os.environ.pop("VR_B", None)
            with self.assertRaises(RuntimeError):
                with ds.env_override({"VR_A": "2", "VR_B": "3"}):
                    self.assertEqual((os.environ["VR_A"], os.environ["VR_B"]), ("2", "3"))
                    raise RuntimeError
            self.assertEqual(os.environ["VR_A"], "1")
            self.assertNotIn("VR_B", os.environ)


if __name__ == "__main__":
    unittest.main()
