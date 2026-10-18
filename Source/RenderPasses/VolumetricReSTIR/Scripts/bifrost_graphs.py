"""Our own Bifrost graphs, built as JSON (user, 2026-10-17: Maya + Bifrost for film-quality volumes; bifrost_export.py
simulates and exports them headless). Each builder returns a Bifrost definition file whose one compound runs an Aero
simulation; bifrost_export.wrap_graph taps its volume (VOLUME_OUTPUT) for the .vdb writer. Units: Bifrost's
scene units, metres (aero_solver_settings.scene_units_in_meters 1); y up, as Maya is.

  vortex_construct: the Lanterns construct -- a smoke column driven round its axis. Smoke is sourced from a disc on the
ground and carried by a prescribed flow, damped toward it by drag (set_influence_force + set_influence_drag: the
velocity settles at force / drag instead of growing without bound): a swirl round the y axis at `swirl` rad/s (up x
the offset from the axis -- solid-body rotation), a pull toward the axis at `pull` per second (the funnel stays tight)
and an updraft of `lift` m/s, shaped by height into a rounded head over a smoky tail; Bifrost's production nodes
add the detail (aero_pyroclastic_influence, aero_einstein_influence) and post_refine_aero the resolution.
"""
NAMESPACE = "Lantern::Graphs"
# nodes taking any number of inputs on `first` as multiInPortNames, as Bifrost's own graphs write them (a fan-in
# declaration there is rejected: "target port not found on node"); simulation nodes' array ports are fan-in
MULTI_IN = {"Core::Math::add", "Core::Math::multiply", "Core::Math::subtract", "Core::Math::min", "Core::Math::max"}


def _f(x):
    return "%sf" % float(x)


def _v3(x, y, z):
    return {"x": _f(x), "y": _f(y), "z": _f(z)}


class Graph:
    """A compound under construction: nodes, connections (fan-in sub-ports declared as they are used) and values."""

    def __init__(self, name):
        self.c = {"name": "%s::%s" % (NAMESPACE, name), "ports": [], "compoundNodes": [], "connections": [], "values": []}
        self.nodes = {}

    def node(self, name, node_type, **values):
        n = {"nodeName": name, "nodeType": node_type}
        self.c["compoundNodes"].append(n)
        self.nodes[name] = n
        for port, (vtype, value) in values.items():
            self.value("%s.%s" % (name, port), vtype, value)
        return name

    def value(self, name, vtype, value):
        self.c["values"].append({"valueName": name, "valueType": vtype, "value": value})

    def connect(self, source, target):
        parts = target.split(".")
        if len(parts) == 3:  # node.port.sub_port
            n = self.nodes[parts[0]]
            if n["nodeType"] in MULTI_IN:
                subs = n.setdefault("multiInPortNames", [])
            else:
                subs = n.setdefault("fanInPortNames", {}).setdefault(parts[1], [])
            if parts[2] not in subs:
                subs.append(parts[2])
        self.c["connections"].append({"source": source, "target": target})

    def output(self, name, vtype, source):
        self.c["ports"].append({"portName": name, "portDirection": "output", "portType": vtype})
        self.connect(source, "." + name)

    def definition(self):
        return {"header": {"metadata": [{"metaName": "adskFileFormatVersion", "metaValue": "100L"}]},
                "namespaces": [], "types": [], "compounds": [self.c]}


def check_graph(compound):
    """Problems with a compound's wiring: a connection to or from a node it does not have, or into a fan-in sub-port
    its node does not declare. Empty when well formed."""
    nodes = {n["nodeName"]: n for n in compound.get("compoundNodes", [])}
    ports = {p["portName"] for p in compound.get("ports", [])}
    problems = []
    for conn in compound.get("connections", []):
        for end in (conn["source"], conn["target"]):
            name = end.split(".")[0]
            if end.startswith("."):
                if end[1:].split(".")[0] not in ports:
                    problems.append("no port %s" % end)
            elif name not in nodes:
                problems.append("no node %s (%s -> %s)" % (name, conn["source"], conn["target"]))
        parts = conn["target"].split(".")
        if len(parts) == 3 and parts[0] in nodes:
            n = nodes[parts[0]]
            declared = n.get("fanInPortNames", {}).get(parts[1], []) + n.get("multiInPortNames", [])
            if parts[2] not in declared:
                problems.append("%s.%s.%s is not a declared fan-in sub-port" % tuple(parts))
    return problems


VOLUME_OUTPUT = "refine.refined_aero"  # what bifrost_export.py writes: the refined volume
SIM_VOLUME_OUTPUT = "simulate_aero.aero_volume"  # ... or, refined inside the simulation (sim_refine), the solver's own


def vortex_construct(detail=0.03, swirl=1.5, pull=0.3, lift=2.5, drag=2.0, source_radius=1.0, fog=2.0, temperature=60.0,
                     core=1.2, cap=9.0, fade_length=3.0, head_push=0.0, base_pull=1.0, base_height=4.0,
                     bend=0.0, bend_from=6.0, bend_length=3.0,
                     tail_radius=2.2, tail_fog=0.0, source_noise=0.0, noise_frequency=2.0, tail_thin=0.0,
                     source_arms=0, source_arm_amp=0.8,
                     pyro_drag=1.5, pyro_vorticity=4.0, pyro_frequency=1.0, einstein=1.0, vorticity=0.3,
                     refine_levels=1, style="busy", height=14.0, width=12.0,
                     sim_refine=0, sharpening=None, einstein_fine=None, einstein_coarse=None, einstein_frequency=None):
    """The Lanterns construct as an Aero simulation (module docstring), with Bifrost's production detail.
    The flow, reached through `drag` (1/s) and confined to the vortex's core (x exp(-|r|^2 / `core`^2), r the offset
    from the axis: spun as a solid body, the whole domain flung the head into a 12 m sheet): a swirl round the y axis
    at `swirl` rad/s; an updraft of `lift` m/s that fades out between `cap` - `fade_length` and `cap` (m), so the
    column stops rising and rolls into a rotating head; a pull toward the axis at `pull` per second, x (1 - head_push
    (1 - fade)) -- kept at the head by default, outward there for head_push > 1 -- and x (base_pull + (1 - base_pull)
    clamp(y / base_height, 0, 1)): weaker near the ground for base_pull < 1, so the column widens toward its foot (the
    reference's construct widens toward its tail); and, for `bend` > 0, a drift along +x above `bend_from` (m), ramping
    up over `bend_length` (m) to `bend` m/s and faded with the updraft, which bends the column's top (the reference's
    construct is flatter toward its head than its tail). Sources: a disc `source_radius` (m) at fog
    density `fog`, and, if `tail_fog` > 0, a wider, fainter one (`tail_radius`) -- off by default: rising with the
    core it wrapped the whole column in a faint halo rather than making a tail, and filled the renderer's atlas
    (~4560 of 4080 deep by frame 66); for `source_noise` > 0 the main source's fog density is fog + fractal noise
    (magnitude fog x source_noise, `noise_frequency` per m, changing with time) -- an even source leaves the swirl
    nothing to stretch into streaks (it made lumps); for `source_arms` > 0 the source is denser in that many spots
    round its disc (fog x (1 + source_arm_amp cos(n theta))), which the swirl and the updraft wind into helical bands,
    rings where the updraft fades (the reference's construct is ringed); for `tail_thin` > 0 the smoke dissipates at that rate (1/s) near the ground,
    masked by 1 - clamp(y / base_height, 0, 1): the reference's construct thins into smoke toward its tail. Detail: Bifrost's
    aero_pyroclastic_influence (`pyro_drag`, `pyro_vorticity`, `pyro_frequency`: billowy detail) and
    aero_einstein_influence (`einstein`: coarse and fine turbulence), vorticity confinement (`vorticity`), the solver's
    `style` -- the Einstein turbulence's fine and coarse parts and frequency scale (`einstein_fine`, `einstein_coarse`,
    `einstein_frequency`) set apart if given; refinement inside the simulation (aero_refinement_settings, `sim_refine`
    levels, (radius, amount) of `sharpening`): the solver resolves finer detail, Bifrost's own upres; then
    post_refine_aero, `refine_levels` levels (each doubles the resolution of all but the velocity, adding no detail) --
    its output is the volume exported (VOLUME_OUTPUT). The fluid detail size `detail` (m, absolute), inside a `width` x
    `height` x `width` box (m) standing on the ground."""
    g = Graph("vortex_construct")
    for name, radius, density in (("source", source_radius, fog), ("tail", tail_radius, tail_fog))[:2 if tail_fog > 0 else 1]:
        g.node(name + "_disc", "Modeling::Primitive::create_mesh_cylinder", radius=("float", _f(radius)),
               height=("float", _f(0.3)), position=("Math::float3", _v3(0, 0.15, 0)), up_axis=("Math::float3", _v3(0, 1, 0)))
        g.node(name + "_air", "Simulation::Aero::source_air", fluid_detail_size=("float", _f(detail)),
               use_fluid_detail_size=("bool", "true"), resolution_mode=("Geometry::Volume::ResolutionType", "Absolute"),
               fog_density=("float", _f(density)), temperature=("float", _f(temperature)))
        g.connect(name + "_disc.out_mesh", name + "_air.geometry.disc")
    if source_noise > 0 or source_arms > 0:  # a field drives the main source's density: fog + noise + arms
        g.c["values"] = [v for v in g.c["values"] if v["valueName"] != "source_air.fog_density"]
        g.node("src_base", "Core::Fields::scalar_field", value=("float", _f(fog)))
        g.node("src_fog", "Core::Math::add")
        g.connect("src_base.scalar_field", "src_fog.first.base")
        g.connect("src_fog.output", "source_air.fog_density")
    if source_noise > 0:  # fractal noise, changing with time
        g.node("src_time", "Core::Time::time")
        g.node("src_noise", "Core::Fields::fractal_noise_field", magnitude=("float", _f(fog * source_noise)),
               frequency=("float", _f(noise_frequency)))
        g.connect("src_time.seconds", "src_noise.time")
        g.connect("src_noise.noise_field", "src_fog.first.noise")
    if source_arms > 0:  # fog x amp x cos(n atan2(z, x))
        for axis, vec in (("x", (1, 0, 0)), ("z", (0, 0, 1))):
            g.node(axis + "_axis", "Core::Fields::vector_field", value=("Math::float3", _v3(*vec)))
            g.node("pos_" + axis, "Core::Math::dot")
            g.connect("position.position", "pos_%s.first" % axis)
            g.connect("%s_axis.vector_field" % axis, "pos_%s.second" % axis)
        g.node("angle", "Core::Math::atan_2D")
        g.connect("pos_z.dot_product", "angle.y")
        g.connect("pos_x.dot_product", "angle.x")
        g.node("arms_k", "Core::Fields::scalar_field", value=("float", _f(source_arms)))
        g.node("arm_phase", "Core::Math::multiply")
        g.connect("angle.arctangent", "arm_phase.first.angle")
        g.connect("arms_k.scalar_field", "arm_phase.first.k")
        g.node("arm_cos", "Core::Math::cos")
        g.connect("arm_phase.output", "arm_cos.value")
        g.node("arm_amp", "Core::Fields::scalar_field", value=("float", _f(fog * source_arm_amp)))
        g.node("arm_term", "Core::Math::multiply")
        g.connect("arm_cos.cosine", "arm_term.first.cos")
        g.connect("arm_amp.scalar_field", "arm_term.first.k")
        g.connect("arm_term.output", "src_fog.first.arms")
    g.node("bounds", "Modeling::Primitive::create_mesh_cube", length=("float", _f(width)), width=("float", _f(width)),
           height=("float", _f(height)), position=("Math::float3", _v3(0, height / 2, 0)))
    g.node("aero_solver_settings", "Simulation::Aero::aero_solver_settings", scene_units_in_meters=("float", _f(1.0)),
           style=("Simulation::Aero::TransportStyle", style), enable_buoyancy=("bool", "true"),
           kill_voxel_fog_threshold=("float", _f(0.005)))
    g.connect("bounds.cube_mesh", "aero_solver_settings.simulation_bounds")
    if sim_refine:  # refinement inside the simulation: finer detail resolved, not upsampled
        kw = {"enable_refinement": ("bool", "true"), "refinement_levels": ("int", "%dL" % sim_refine)}
        if sharpening:
            kw.update(apply_filter=("bool", "true"), sharpening_radius=("int", "%dL" % sharpening[0]),
                      sharpening_amount=("float", _f(sharpening[1])))
        g.node("sim_refinement", "Simulation::Aero::aero_refinement_settings", **kw)
        g.connect("sim_refinement.refinement_settings", "aero_solver_settings.additional_settings.refinement")
    # the prescribed flow, as a vector field (r: the offset from the y axis; y: the height)
    g.node("position", "Core::Fields::position_field")
    g.node("flat", "Core::Fields::vector_field", value=("Math::float3", _v3(1, 0, 1)))
    g.node("offset", "Core::Math::multiply")
    g.connect("position.position", "offset.first.p")
    g.connect("flat.vector_field", "offset.first.mask")
    g.node("up", "Core::Fields::vector_field", value=("Math::float3", _v3(0, 1, 0)))
    g.node("height", "Core::Math::dot")
    g.connect("position.position", "height.first")
    g.connect("up.vector_field", "height.second")
    # fade = clamp((cap - y) / fade_length, 0, 1)
    g.node("cap_over_fade", "Core::Fields::scalar_field", value=("float", _f(cap / fade_length)))
    g.node("minus_inv_fade", "Core::Fields::scalar_field", value=("float", _f(-1.0 / fade_length)))
    g.node("height_term", "Core::Math::multiply")
    g.connect("height.dot_product", "height_term.first.y")
    g.connect("minus_inv_fade.scalar_field", "height_term.first.k")
    g.node("fade_raw", "Core::Math::add")
    g.connect("cap_over_fade.scalar_field", "fade_raw.first.cap")
    g.connect("height_term.output", "fade_raw.first.y")
    g.node("fade", "Core::Math::clamp", min=("float", _f(0.0)), max=("float", _f(1.0)))
    g.connect("fade_raw.output", "fade.value")
    # the core: exp(-|r|^2 / core^2)
    g.node("r2", "Core::Math::length_squared")
    g.connect("offset.output", "r2.vector")
    g.node("minus_inv_core2", "Core::Fields::scalar_field", value=("float", _f(-1.0 / core ** 2)))
    g.node("core_arg", "Core::Math::multiply")
    g.connect("r2.length_squared", "core_arg.first.r2")
    g.connect("minus_inv_core2.scalar_field", "core_arg.first.k")
    g.node("core", "Core::Math::exponential")
    g.connect("core_arg.output", "core.value")
    # swirl: drag x swirl x (up x r) x core
    g.node("swirl", "Core::Math::cross")
    g.connect("up.vector_field", "swirl.first")
    g.connect("offset.output", "swirl.second")
    g.node("swirl_rate", "Core::Fields::scalar_field", value=("float", _f(drag * swirl)))
    g.node("swirl_force", "Core::Math::multiply")
    g.connect("swirl.cross_product", "swirl_force.first.t")
    g.connect("swirl_rate.scalar_field", "swirl_force.first.k")
    g.connect("core.exponential", "swirl_force.first.core")
    # pull: -drag x pull x r x core x (fade head_push + 1 - head_push)
    g.node("push", "Core::Fields::scalar_field", value=("float", _f(head_push)))
    g.node("one_minus_push", "Core::Fields::scalar_field", value=("float", _f(1.0 - head_push)))
    g.node("pull_scale_raw", "Core::Math::multiply")
    g.connect("fade.clamped", "pull_scale_raw.first.fade")
    g.connect("push.scalar_field", "pull_scale_raw.first.k")
    g.node("pull_scale", "Core::Math::add")
    g.connect("pull_scale_raw.output", "pull_scale.first.scaled")
    g.connect("one_minus_push.scalar_field", "pull_scale.first.push")
    # x (base_pull + (1 - base_pull) clamp(y / base_height, 0, 1))
    g.node("inv_base_height", "Core::Fields::scalar_field", value=("float", _f(1.0 / base_height)))
    g.node("ramp_raw", "Core::Math::multiply")
    g.connect("height.dot_product", "ramp_raw.first.y")
    g.connect("inv_base_height.scalar_field", "ramp_raw.first.k")
    g.node("ramp", "Core::Math::clamp", min=("float", _f(0.0)), max=("float", _f(1.0)))
    g.connect("ramp_raw.output", "ramp.value")
    g.node("base_pull", "Core::Fields::scalar_field", value=("float", _f(base_pull)))
    g.node("one_minus_base_pull", "Core::Fields::scalar_field", value=("float", _f(1.0 - base_pull)))
    g.node("base_scale_raw", "Core::Math::multiply")
    g.connect("ramp.clamped", "base_scale_raw.first.ramp")
    g.connect("one_minus_base_pull.scalar_field", "base_scale_raw.first.k")
    g.node("base_scale", "Core::Math::add")
    g.connect("base_scale_raw.output", "base_scale.first.ramped")
    g.connect("base_pull.scalar_field", "base_scale.first.floor")
    g.node("pull_rate", "Core::Fields::scalar_field", value=("float", _f(-drag * pull)))
    g.node("pull_force", "Core::Math::multiply")
    g.connect("offset.output", "pull_force.first.r")
    g.connect("pull_rate.scalar_field", "pull_force.first.k")
    g.connect("pull_scale.output", "pull_force.first.scale")
    g.connect("core.exponential", "pull_force.first.core")
    g.connect("base_scale.output", "pull_force.first.base")
    # lift: drag x lift x up x fade x core
    g.node("lift_vector", "Core::Fields::vector_field", value=("Math::float3", _v3(0, drag * lift, 0)))
    g.node("lift_force", "Core::Math::multiply")
    g.connect("lift_vector.vector_field", "lift_force.first.lift")
    g.connect("fade.clamped", "lift_force.first.fade")
    g.connect("core.exponential", "lift_force.first.core")
    g.node("flow", "Core::Math::add")
    g.connect("swirl_force.output", "flow.first.swirl")
    g.connect("pull_force.output", "flow.first.pull")
    g.connect("lift_force.output", "flow.first.lift")
    if bend:  # drag x bend x (1, 0, 0) x clamp((y - bend_from) / bend_length, 0, 1); either sign
        g.node("inv_bend_length", "Core::Fields::scalar_field", value=("float", _f(1.0 / bend_length)))
        g.node("bend_offset", "Core::Fields::scalar_field", value=("float", _f(-bend_from / bend_length)))
        g.node("bend_raw", "Core::Math::multiply")
        g.connect("height.dot_product", "bend_raw.first.y")
        g.connect("inv_bend_length.scalar_field", "bend_raw.first.k")
        g.node("bend_shift", "Core::Math::add")
        g.connect("bend_raw.output", "bend_shift.first.scaled")
        g.connect("bend_offset.scalar_field", "bend_shift.first.offset")
        g.node("bend_ramp", "Core::Math::clamp", min=("float", _f(0.0)), max=("float", _f(1.0)))
        g.connect("bend_shift.output", "bend_ramp.value")
        g.node("bend_vector", "Core::Fields::vector_field", value=("Math::float3", _v3(drag * bend, 0, 0)))
        g.node("bend_force", "Core::Math::multiply")
        g.connect("bend_vector.vector_field", "bend_force.first.drift")
        g.connect("bend_ramp.clamped", "bend_force.first.ramp")
        g.connect("fade.clamped", "bend_force.first.fade")  # none in the cap: the head would slide into a hook
        g.connect("bend_force.output", "flow.first.bend")
    g.node("vortex_force", "Simulation::Influence::set_influence_force")
    g.connect("flow.output", "vortex_force.force")
    g.node("vortex_drag", "Simulation::Influence::set_influence_drag", drag=("float", _f(drag)))
    g.connect("vortex_force.out_influence", "vortex_drag.influence")
    # Bifrost's production detail
    g.node("pyroclastic", "Simulation::Influence::aero_pyroclastic_influence", drag=("float", _f(pyro_drag)),
           vorticity=("float", _f(pyro_vorticity)), frequency=("float", _f(pyro_frequency)))
    ekw = {k: ("float", _f(v)) for k, v in (("fine_turbulence", einstein_fine), ("coarse_turbulence", einstein_coarse),
                                             ("frequency_scale", einstein_frequency)) if v is not None}
    g.node("einstein", "Simulation::Influence::aero_einstein_influence", master_magnitude=("float", _f(einstein)), **ekw)
    g.node("vorticity", "Simulation::Influence::vorticity_influence", vorticity=("float", _f(vorticity)))
    g.node("simulate_aero", "Simulation::Aero::simulate_aero")
    g.connect("source_air.air_source", "simulate_aero.sources.air")
    if tail_fog > 0:
        g.connect("tail_air.air_source", "simulate_aero.sources.tail")
    g.connect("aero_solver_settings.solver_settings", "simulate_aero.settings")
    g.connect("vortex_drag.out_influence", "simulate_aero.influences.vortex")
    g.connect("pyroclastic.drag_influence", "simulate_aero.influences.pyro_drag")
    g.connect("pyroclastic.vorticity_influence", "simulate_aero.influences.pyro_vorticity")
    g.connect("einstein.turbulence_influence", "simulate_aero.influences.einstein_turbulence")
    g.connect("einstein.vorticity_influence", "simulate_aero.influences.einstein_vorticity")
    g.connect("vorticity.out_influence", "simulate_aero.influences.vorticity")
    if tail_thin > 0:  # dissipation near the ground: 1 - ramp
        g.node("minus_one", "Core::Fields::scalar_field", value=("float", _f(-1.0)))
        g.node("one", "Core::Fields::scalar_field", value=("float", _f(1.0)))
        g.node("neg_ramp", "Core::Math::multiply")
        g.connect("ramp.clamped", "neg_ramp.first.ramp")
        g.connect("minus_one.scalar_field", "neg_ramp.first.k")
        g.node("low", "Core::Math::add")
        g.connect("one.scalar_field", "low.first.one")
        g.connect("neg_ramp.output", "low.first.minus_ramp")
        g.node("tail_mask", "Simulation::Influence::set_influence_mask")
        g.connect("low.output", "tail_mask.mask")
        g.node("tail_dissipation", "Simulation::Influence::dissipation_influence", rate=("float", _f(tail_thin)))
        g.connect("tail_mask.out_influence", "tail_dissipation.influence")
        g.connect("tail_dissipation.out_influence", "simulate_aero.influences.tail_thin")
    g.node("refine", "Simulation::Aero::post_refine_aero", refinement_levels=("int", "%dL" % refine_levels))
    g.connect("simulate_aero.aero_volume", "refine.aero_volume")
    g.connect("simulate_aero.solver_inputs", "refine.solver_inputs")
    g.output("volume", "Object", VOLUME_OUTPUT)
    return g.definition()


BUILDERS = {"vortex_construct": vortex_construct}


def main(argv):
    """python bifrost_graphs.py <builder> <out.json> [param=value ...] -- writes the graph for bifrost_export.py
    (its compound: Lantern::Graphs::<builder>, its volume: VOLUME_OUTPUT)."""
    import json
    params = {}
    for a in argv[3:]:
        k, v = a.split("=", 1)
        params[k] = tuple(float(x) for x in v.split(",")) if "," in v else float(v)
    with open(argv[2], "w", encoding="utf-8") as fh:
        json.dump(BUILDERS[argv[1]](**params), fh, indent=1)
    print(argv[2])


if __name__ == "__main__":
    import sys
    main(sys.argv)
