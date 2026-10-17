"""bifrost_graphs.py: our own Bifrost graphs, as JSON (no Maya needed to check their shape)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bifrost_export as bx  # noqa: E402
import bifrost_graphs as bg  # noqa: E402


class TestWellFormed(unittest.TestCase):
    def test_check_graph_finds_a_dangling_connection_and_an_undeclared_fan_in(self):
        c = {"name": "x", "compoundNodes": [{"nodeName": "a", "nodeType": "Core::Math::add", "fanInPortNames": {"first": ["p"]}}],
             "connections": [{"source": "b.out", "target": "a.first.p"}, {"source": "a.output", "target": "a.first.q"}]}
        problems = bg.check_graph(c)
        self.assertTrue(any("b" in p for p in problems), problems)  # no node b
        self.assertTrue(any("first.q" in p for p in problems), problems)  # q is not a declared sub-port of a.first


class TestVortexConstruct(unittest.TestCase):
    """The Lanterns construct as an Aero simulation (user, 2026-10-17): a smoke column driven round its axis."""

    def setUp(self):
        self.d = bg.vortex_construct()
        self.c = self.d["compounds"][0]
        self.nodes = {n["nodeName"]: n for n in self.c["compoundNodes"]}
        self.values = {v["valueName"]: v for v in self.c["values"]}

    def test_is_well_formed(self):
        self.assertEqual(bg.check_graph(self.c), [])
        self.assertEqual(self.c["name"], bg.NAMESPACE + "::vortex_construct")

    def test_smoke_is_sourced_and_simulated_by_aero(self):
        types = {n["nodeType"] for n in self.c["compoundNodes"]}
        self.assertTrue({"Simulation::Aero::source_air", "Simulation::Aero::simulate_aero",
                         "Simulation::Aero::aero_solver_settings"} <= types)
        conns = {(c["source"], c["target"]) for c in self.c["connections"]}
        self.assertIn(("source_air.air_source", "simulate_aero.sources.air"), conns)
        self.assertIn(("aero_solver_settings.solver_settings", "simulate_aero.settings"), conns)

    def test_the_flow_is_driven_round_the_axis_with_drag(self):
        # a force field (swirl round the axis + pull toward it + updraft) damped by drag: the velocity settles at
        # force / drag rather than growing without bound
        conns = {(c["source"], c["target"]) for c in self.c["connections"]}
        self.assertEqual(self.nodes["vortex_force"]["nodeType"], "Simulation::Influence::set_influence_force")
        self.assertEqual(self.nodes["vortex_drag"]["nodeType"], "Simulation::Influence::set_influence_drag")
        self.assertIn(("vortex_force.out_influence", "vortex_drag.influence"), conns)
        self.assertIn(("vortex_drag.out_influence", "simulate_aero.influences.vortex"), conns)
        self.assertEqual(self.nodes["swirl"]["nodeType"], "Core::Math::cross")  # up x (offset from the axis)
        self.assertIn(("flow.output", "vortex_force.force"), conns)

    def test_parameters_become_typed_bifrost_values(self):
        d = bg.vortex_construct(detail=0.04, swirl=2.0)
        values = {v["valueName"]: v for v in d["compounds"][0]["values"]}
        self.assertEqual(values["source_air.fluid_detail_size"], {"valueName": "source_air.fluid_detail_size", "valueType": "float", "value": "0.04f"})
        self.assertEqual(values["swirl_rate.value"]["value"], "4.0f")  # the force: drag (2) x swirl (2)
        self.assertEqual(values["up.value"]["valueType"], "Math::float3")
        # the detail size in metres, not relative to the source's bounds (left at its default the volume came out
        # at 0.15 m voxels for a 0.05 m detail size)
        self.assertEqual(values["source_air.resolution_mode"]["value"], "Absolute")

    def test_math_nodes_declare_their_inputs_as_multi_in_ports(self):
        # Core::Math::add / multiply take any number of inputs on `first` as multiInPortNames (as Bifrost's own graphs
        # write them); fanInPortNames there is rejected ("target port not found on node")
        for name in ("offset", "swirl_force", "pull_force", "flow"):
            self.assertNotIn("fanInPortNames", self.nodes[name], name)
        self.assertEqual(self.nodes["flow"]["multiInPortNames"], ["swirl", "pull", "lift"])
        self.assertEqual(self.nodes["source_air"]["fanInPortNames"], {"geometry": ["disc"]})  # simulation nodes: fan-in

    def test_exports_through_the_wrapper(self):
        w = bx.wrap_graph(self.d, self.c["name"], "simulate_aero.aero_volume", "C:/out", "construct", {})
        self.assertEqual(bg.check_graph(w["compounds"][0]), [])


if __name__ == "__main__":
    unittest.main()
