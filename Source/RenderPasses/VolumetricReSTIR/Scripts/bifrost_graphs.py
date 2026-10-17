"""Our own Bifrost graphs, built as JSON (user, 2026-10-17: Maya + Bifrost for film-quality volumes; bifrost_export.py
simulates and exports them headless). Each builder returns a Bifrost definition file whose one compound runs an Aero
simulation; bifrost_export.wrap_graph taps its volume (simulate_aero.aero_volume) for the .vdb writer. Units: Bifrost's
scene units, metres (aero_solver_settings.scene_units_in_meters 1); y up, as Maya is.

  vortex_construct: the Lanterns construct -- a smoke column driven round its axis. Smoke is sourced from a disc on the
ground and carried by a prescribed flow, damped toward it by drag (set_influence_force + set_influence_drag: the
velocity settles at force / drag instead of growing without bound): a swirl round the y axis at `swirl` rad/s (up x
the offset from the axis -- solid-body rotation), a pull toward the axis at `pull` per second (the funnel stays tight)
and an updraft of `lift` m/s; Aero's turbulence and vorticity confinement add the small-scale detail.
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


def vortex_construct(detail=0.05, swirl=1.5, pull=0.3, lift=2.5, drag=2.0, source_radius=1.5, fog=2.0, temperature=60.0,
                     turbulence=(1.5, 3.0), vorticity=0.3, height=14.0, width=12.0):
    """The Lanterns construct as an Aero simulation (module docstring): `detail` the fluid detail size (m), the flow's
    `swirl` (rad/s), `pull` (1/s) and `lift` (m/s) reached through `drag` (1/s), the source disc's radius (m), its fog
    density and temperature, the turbulence at two scales and the vorticity confinement, inside a `width` x `height` x
    `width` box (m) standing on the ground."""
    g = Graph("vortex_construct")
    g.node("source_disc", "Modeling::Primitive::create_mesh_cylinder", radius=("float", _f(source_radius)),
           height=("float", _f(0.3)), position=("Math::float3", _v3(0, 0.15, 0)), up_axis=("Math::float3", _v3(0, 1, 0)))
    g.node("source_air", "Simulation::Aero::source_air", fluid_detail_size=("float", _f(detail)),
           use_fluid_detail_size=("bool", "true"), resolution_mode=("Geometry::Volume::ResolutionType", "Absolute"),
           fog_density=("float", _f(fog)), temperature=("float", _f(temperature)))
    g.connect("source_disc.out_mesh", "source_air.geometry.disc")
    g.node("bounds", "Modeling::Primitive::create_mesh_cube", length=("float", _f(width)), width=("float", _f(width)),
           height=("float", _f(height)), position=("Math::float3", _v3(0, height / 2, 0)))
    g.node("aero_solver_settings", "Simulation::Aero::aero_solver_settings", scene_units_in_meters=("float", _f(1.0)),
           style=("Simulation::Aero::TransportStyle", "busy"), enable_buoyancy=("bool", "true"),
           kill_voxel_fog_threshold=("float", _f(0.005)))
    g.connect("bounds.cube_mesh", "aero_solver_settings.simulation_bounds")
    # the prescribed flow, as a vector field: drag x (swirl (up x r) - pull r + lift up), r the offset from the y axis
    g.node("position", "Core::Fields::position_field")
    g.node("flat", "Core::Fields::vector_field", value=("Math::float3", _v3(1, 0, 1)))
    g.node("offset", "Core::Math::multiply")
    g.connect("position.position", "offset.first.p")
    g.connect("flat.vector_field", "offset.first.mask")
    g.node("up", "Core::Fields::vector_field", value=("Math::float3", _v3(0, 1, 0)))
    g.node("swirl", "Core::Math::cross")
    g.connect("up.vector_field", "swirl.first")
    g.connect("offset.output", "swirl.second")
    g.node("swirl_rate", "Core::Fields::scalar_field", value=("float", _f(drag * swirl)))
    g.node("swirl_force", "Core::Math::multiply")
    g.connect("swirl.cross_product", "swirl_force.first.t")
    g.connect("swirl_rate.scalar_field", "swirl_force.first.k")
    g.node("pull_rate", "Core::Fields::scalar_field", value=("float", _f(-drag * pull)))
    g.node("pull_force", "Core::Math::multiply")
    g.connect("offset.output", "pull_force.first.r")
    g.connect("pull_rate.scalar_field", "pull_force.first.k")
    g.node("lift_force", "Core::Fields::vector_field", value=("Math::float3", _v3(0, drag * lift, 0)))
    g.node("flow", "Core::Math::add")
    g.connect("swirl_force.output", "flow.first.swirl")
    g.connect("pull_force.output", "flow.first.pull")
    g.connect("lift_force.vector_field", "flow.first.lift")
    g.node("vortex_force", "Simulation::Influence::set_influence_force")
    g.connect("flow.output", "vortex_force.force")
    g.node("vortex_drag", "Simulation::Influence::set_influence_drag", drag=("float", _f(drag)))
    g.connect("vortex_force.out_influence", "vortex_drag.influence")
    g.node("turbulence", "Simulation::Influence::turbulence_influence", turbulence=("float", _f(turbulence[0])),
           frequency=("float", _f(0.5)), change_rate=("float", _f(1.0)))
    g.node("turbulence_fine", "Simulation::Influence::turbulence_influence", turbulence=("float", _f(turbulence[1])),
           frequency=("float", _f(2.0)), change_rate=("float", _f(2.0)))
    g.node("vorticity", "Simulation::Influence::vorticity_influence", vorticity=("float", _f(vorticity)))
    g.node("simulate_aero", "Simulation::Aero::simulate_aero")
    g.connect("source_air.air_source", "simulate_aero.sources.air")
    g.connect("aero_solver_settings.solver_settings", "simulate_aero.settings")
    g.connect("vortex_drag.out_influence", "simulate_aero.influences.vortex")
    g.connect("turbulence.out_influence", "simulate_aero.influences.turbulence")
    g.connect("turbulence_fine.out_influence", "simulate_aero.influences.turbulence_fine")
    g.connect("vorticity.out_influence", "simulate_aero.influences.vorticity")
    g.output("volume", "Object", "simulate_aero.aero_volume")
    return g.definition()


BUILDERS = {"vortex_construct": vortex_construct}


def main(argv):
    """python bifrost_graphs.py <builder> <out.json> [param=value ...] -- writes the graph for bifrost_export.py
    (its compound: Lantern::Graphs::<builder>, its volume: simulate_aero.aero_volume)."""
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
