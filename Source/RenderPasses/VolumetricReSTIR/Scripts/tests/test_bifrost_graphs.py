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

    def test_the_flow_is_confined_to_the_vortex_core(self):
        # swirl, pull and updraft x exp(-|r|^2 / core^2): the air round the column is left still (spun as a solid body
        # the whole domain flung the head into a 12 m sheet)
        conns = {(c["source"], c["target"]) for c in self.c["connections"]}
        self.assertEqual(self.nodes["r2"]["nodeType"], "Core::Math::length_squared")
        self.assertEqual(self.nodes["core"]["nodeType"], "Core::Math::exponential")
        for force in ("swirl_force", "pull_force", "lift_force"):
            self.assertIn(("core.exponential", "%s.first.core" % force), conns, force)
        d = bg.vortex_construct(core=2.0)
        v = {x["valueName"]: x["value"] for x in d["compounds"][0]["values"]}
        self.assertEqual(v["minus_inv_core2.value"], "-0.25f")

    def test_the_pull_ramps_up_from_the_ground(self):
        # the reference's construct widens toward its tail: the pull starts at `base_pull` of itself on the ground and
        # reaches full strength at `base_height` (ramp = clamp(y / base_height, 0, 1); x (base_pull + (1 - base_pull) ramp))
        conns = {(c["source"], c["target"]) for c in self.c["connections"]}
        self.assertEqual(self.nodes["ramp"]["nodeType"], "Core::Math::clamp")
        self.assertIn(("base_scale.output", "pull_force.first.base"), conns)
        d = bg.vortex_construct(base_pull=0.25, base_height=4.0)
        v = {x["valueName"]: x["value"] for x in d["compounds"][0]["values"]}
        self.assertEqual(v["inv_base_height.value"], "0.25f")
        self.assertEqual((v["base_pull.value"], v["one_minus_base_pull.value"]), ("0.25f", "0.75f"))
        self.assertEqual(bg.check_graph(d["compounds"][0]), [])

    def test_a_drift_above_a_height_bends_the_column(self):
        # the reference's construct is flatter toward its head than its tail: above `bend_from` the air drifts along +x,
        # ramping up over `bend_length` to `bend` m/s (through the same drag); no drift by default
        self.assertNotIn("bend_ramp", self.nodes)
        d = bg.vortex_construct(bend=1.0, bend_from=6.0, bend_length=3.0)
        c = d["compounds"][0]
        nodes = {n["nodeName"]: n for n in c["compoundNodes"]}
        conns = {(x["source"], x["target"]) for x in c["connections"]}
        self.assertEqual(nodes["bend_ramp"]["nodeType"], "Core::Math::clamp")
        self.assertIn(("bend_force.output", "flow.first.bend"), conns)
        # faded with the updraft: in the cap, where the column has stopped rising, a drift slid the head into a hook
        self.assertIn(("fade.clamped", "bend_force.first.fade"), conns)
        v = {x["valueName"]: x["value"] for x in c["values"]}
        self.assertEqual(v["bend_vector.value"], {"x": "2.0f", "y": "0.0f", "z": "0.0f"})  # drag 2 x 1 m/s
        self.assertEqual((v["bend_offset.value"], v["inv_bend_length.value"]), ("-2.0f", "%sf" % (1.0 / 3.0)))
        self.assertEqual(bg.check_graph(c), [])

    def test_a_noisy_source_gives_the_swirl_something_to_streak(self):
        # an even source leaves the swirl nothing to stretch; Bifrost's way (its fire feeds fields into source_air):
        # fog density = fog + fractal noise (magnitude fog x source_noise), changing with time; off by default
        self.assertNotIn("src_noise", self.nodes)
        d = bg.vortex_construct(source_noise=0.8, noise_frequency=2.0)
        c = d["compounds"][0]
        nodes = {n["nodeName"]: n for n in c["compoundNodes"]}
        conns = {(x["source"], x["target"]) for x in c["connections"]}
        self.assertEqual(nodes["src_noise"]["nodeType"], "Core::Fields::fractal_noise_field")
        self.assertIn(("src_time.seconds", "src_noise.time"), conns)
        self.assertIn(("src_fog.output", "source_air.fog_density"), conns)
        v = {x["valueName"]: x["value"] for x in c["values"]}
        self.assertEqual((v["src_noise.magnitude"], v["src_noise.frequency"]), ("1.6f", "2.0f"))  # fog 2 x 0.8
        self.assertNotIn("source_air.fog_density", v)  # the field drives it
        self.assertEqual(bg.check_graph(c), [])

    def test_the_tail_thins_near_the_ground(self):
        # the reference's construct thins into smoke toward its tail (the column's foot here): dissipation at
        # `tail_thin` per second, masked by 1 - clamp(y / base_height, 0, 1); none by default
        self.assertNotIn("tail_dissipation", self.nodes)
        d = bg.vortex_construct(tail_thin=0.6, base_height=5.0)
        c = d["compounds"][0]
        nodes = {n["nodeName"]: n for n in c["compoundNodes"]}
        conns = {(x["source"], x["target"]) for x in c["connections"]}
        self.assertEqual(nodes["tail_mask"]["nodeType"], "Simulation::Influence::set_influence_mask")
        self.assertEqual(nodes["tail_dissipation"]["nodeType"], "Simulation::Influence::dissipation_influence")
        self.assertIn(("low.output", "tail_mask.mask"), conns)
        self.assertIn(("tail_mask.out_influence", "tail_dissipation.influence"), conns)
        self.assertIn(("tail_dissipation.out_influence", "simulate_aero.influences.tail_thin"), conns)
        v = {x["valueName"]: x["value"] for x in c["values"]}
        self.assertEqual(v["tail_dissipation.rate"], "0.6f")
        self.assertEqual(bg.check_graph(c), [])

    def test_arms_in_the_source_wind_into_bands(self):
        # the reference's rings: a source denser in `source_arms` spots round its disc (fog x (1 + amp cos(n theta)),
        # theta = atan2(z, x)) -- turned by the swirl and lifted, they wind into helical bands, rings where the
        # updraft fades; time noise in the source made lumps instead
        self.assertNotIn("angle", self.nodes)
        d = bg.vortex_construct(source_arms=6, source_arm_amp=0.8)
        c = d["compounds"][0]
        nodes = {n["nodeName"]: n for n in c["compoundNodes"]}
        conns = {(x["source"], x["target"]) for x in c["connections"]}
        self.assertEqual(nodes["angle"]["nodeType"], "Core::Math::atan_2D")
        self.assertIn(("pos_z.dot_product", "angle.y"), conns)
        self.assertIn(("pos_x.dot_product", "angle.x"), conns)
        self.assertIn(("arm_cos.cosine", "arm_term.first.cos"), conns)
        self.assertIn(("arm_term.output", "src_fog.first.arms"), conns)
        self.assertIn(("src_fog.output", "source_air.fog_density"), conns)
        v = {x["valueName"]: x["value"] for x in c["values"]}
        self.assertEqual((v["arms_k.value"], v["arm_amp.value"]), ("6.0f", "1.6f"))  # fog 2 x 0.8
        self.assertEqual(bg.check_graph(c), [])

    def test_the_updraft_fades_at_the_cap_and_the_head_widens(self):
        # the head rolls into a rotating cap instead of spraying sheets: the updraft x fade, fade = clamp((cap - y) /
        # fade_length, 0, 1); the pull toward the axis x (1 - head_push (1 - fade)): kept at the head by default
        conns = {(c["source"], c["target"]) for c in self.c["connections"]}
        self.assertEqual(self.nodes["height"]["nodeType"], "Core::Math::dot")
        self.assertIn(("position.position", "height.first"), conns)
        self.assertEqual(self.nodes["fade"]["nodeType"], "Core::Math::clamp")
        self.assertEqual((self.values["fade.min"]["value"], self.values["fade.max"]["value"]), ("0.0f", "1.0f"))
        self.assertIn(("fade.clamped", "lift_force.first.fade"), conns)
        self.assertIn(("fade.clamped", "pull_scale_raw.first.fade"), conns)
        self.assertIn(("pull_scale.output", "pull_force.first.scale"), conns)
        d = bg.vortex_construct(cap=9.0, fade_length=3.0, head_push=1.5)
        v = {x["valueName"]: x["value"] for x in d["compounds"][0]["values"]}
        self.assertEqual(v["cap_over_fade.value"], "3.0f")
        self.assertEqual(v["minus_inv_fade.value"], "%sf" % (-1.0 / 3.0))
        # pull scale = fade x head_push + (1 - head_push): 1 low down, 1 - head_push (here outward, -0.5) at the cap
        self.assertEqual((v["push.value"], v["one_minus_push.value"]), ("1.5f", "-0.5f"))
        self.assertEqual(bg.vortex_construct()["compounds"][0]["values"][0]["valueName"].split(".")[0], "source_disc")

    def test_the_faint_wide_source_is_opt_in(self):
        # rising with the core it wrapped the whole column in a faint 2.2 m halo -- no tail, and past the renderer's
        # atlas (~4560 of 4080 deep by frame 66) -- so it is off unless asked for
        self.assertNotIn("tail_air", self.nodes)
        d = bg.vortex_construct(tail_fog=0.5)
        c = d["compounds"][0]
        conns = {(x["source"], x["target"]) for x in c["connections"]}
        self.assertIn(("tail_air.air_source", "simulate_aero.sources.tail"), conns)
        self.assertEqual(bg.check_graph(c), [])

    def test_production_detail_and_refinement(self):
        # Bifrost's pyroclastic and Einstein influences for the detail, then post_refine_aero for resolution; the
        # exported volume is the refined one
        conns = {(c["source"], c["target"]) for c in self.c["connections"]}
        for out in ("pyroclastic.drag_influence", "pyroclastic.vorticity_influence", "einstein.turbulence_influence",
                    "einstein.vorticity_influence"):
            self.assertTrue(any(src == out and tgt.startswith("simulate_aero.influences.") for src, tgt in conns), out)
        self.assertEqual(self.nodes["refine"]["nodeType"], "Simulation::Aero::post_refine_aero")
        self.assertIn(("simulate_aero.aero_volume", "refine.aero_volume"), conns)
        self.assertIn(("simulate_aero.solver_inputs", "refine.solver_inputs"), conns)
        self.assertIn(("refine.refined_aero", ".volume"), conns)
        self.assertEqual(bg.VOLUME_OUTPUT, "refine.refined_aero")

    def test_exports_through_the_wrapper(self):
        w = bx.wrap_graph(self.d, self.c["name"], bg.VOLUME_OUTPUT, "C:/out", "construct", {})
        self.assertEqual(bg.check_graph(w["compounds"][0]), [])


if __name__ == "__main__":
    unittest.main()
